"""Learning loop: train a match classifier on steward decisions and track it in MLflow."""
from __future__ import annotations

import os

import pandas as pd

FEATURES = ["name_similarity", "tax_eq", "tax_conflict", "city_eq", "phone_eq", "domain_eq"]
MODEL_NAME = "goldenrecord-matcher"


MIN_STEWARD_LABELS = 20
AUTO_LABELS_PER_CLASS = 500


def training_set(pairs: pd.DataFrame, decisions: pd.DataFrame) -> pd.DataFrame:
    """Steward labels, topped up with clear-cut automatic labels (HIGH = match, LOW = no match).

    The review queue only holds uncertain pairs, so steward labels alone are often one-sided.
    """
    if decisions.empty:
        decisions = pd.DataFrame(columns=["left_key", "right_key", "decision", "decided_at"])
    latest = decisions.sort_values("decided_at").drop_duplicates(["left_key", "right_key"], keep="last")
    steward = latest.merge(pairs, on=["left_key", "right_key"])
    steward = steward.assign(y=(steward["decision"] == "match").astype(int), label_source="steward")
    if "decided_by" in pairs:  # pairs decided by a steward-approved match pattern are steward labels too
        by_pattern = pairs[pairs["decided_by"].astype(str).str.startswith("MATCH:")]
        done = set(zip(steward["left_key"], steward["right_key"]))
        keep = pd.Series([(a, b) not in done for a, b in zip(by_pattern["left_key"], by_pattern["right_key"])],
                         index=by_pattern.index, dtype=bool)
        by_pattern = by_pattern.loc[keep]
        steward = pd.concat([steward, by_pattern.assign(y=by_pattern["merge"].astype(int), label_source="steward")],
                            ignore_index=True)
    labelled = set(zip(steward["left_key"], steward["right_key"]))
    rest = pairs[[(a, b) not in labelled for a, b in zip(pairs["left_key"], pairs["right_key"])]]
    auto = []
    for band, y in (("HIGH", 1), ("LOW", 0)):
        part = rest[rest["band"] == band]
        auto.append(part.sample(min(len(part), AUTO_LABELS_PER_CLASS), random_state=42).assign(y=y, label_source="auto"))
    return pd.concat([steward, *auto], ignore_index=True)


def train_matcher(pairs: pd.DataFrame, decisions: pd.DataFrame, tracking_uri: str | None = None) -> dict:
    """Fit logistic regression on labelled pairs; log params, metrics and the model to MLflow."""
    import mlflow
    import mlflow.sklearn
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import precision_score, recall_score
    from sklearn.model_selection import train_test_split

    data = training_set(pairs, decisions)
    n_steward = int((data["label_source"] == "steward").sum())
    if n_steward < MIN_STEWARD_LABELS or data["y"].nunique() < 2:
        return {"ok": False, "error": f"need at least {MIN_STEWARD_LABELS} steward decisions (have {n_steward})"}

    X, y = data[FEATURES].astype(float), data["y"]
    stratify = y if y.value_counts().min() >= 2 else None
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.25, random_state=42, stratify=stratify)
    model = LogisticRegression(max_iter=1000).fit(X_train, y_train)
    pred = model.predict(X_test)
    metrics = {"precision": float(precision_score(y_test, pred, zero_division=0)),
               "recall": float(recall_score(y_test, pred, zero_division=0)),
               "n_labels": float(len(data)), "n_steward_labels": float(n_steward), "match_share": float(y.mean())}

    # "fabric": keep the workspace's built-in MLflow tracking (Fabric Data Science) untouched.
    if tracking_uri != "fabric":
        uri = tracking_uri or os.environ.get("MLFLOW_TRACKING_URI", "file:./mlruns")
        if uri.startswith("file:"):
            # Local runs without a tracking server; the Docker harness uses the MLflow server instead.
            os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
        mlflow.set_tracking_uri(uri)
    mlflow.set_experiment(MODEL_NAME)
    with mlflow.start_run() as run:
        mlflow.log_params({"features": ",".join(FEATURES), "model": "LogisticRegression"})
        mlflow.log_metrics(metrics)
        mlflow.log_dict(dict(zip(FEATURES, model.coef_[0].round(4).tolist())), "coefficients.json")
        mlflow.sklearn.log_model(model, name="model", registered_model_name=MODEL_NAME)
        run_id = run.info.run_id
    return {"ok": True, "mlflow_run_id": run_id, **metrics,
            "coefficients": dict(zip(FEATURES, model.coef_[0].round(3).tolist()))}
