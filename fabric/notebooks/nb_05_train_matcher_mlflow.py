# Fabric notebook: nb_05_train_matcher_mlflow  (pandas + scikit-learn + MLflow)
# Deliverable 3 (second half): steward decisions become labelled training data. This notebook
# trains a small match classifier on them and registers it, so the thresholds improve over time.

# %% Imports
import mlflow
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_score, recall_score
from sklearn.model_selection import train_test_split

FEATURES = ["name_similarity", "tax_eq", "tax_conflict", "city_eq", "phone_eq", "domain_eq"]

pairs = spark.table("silver_match_pairs").toPandas()
labels = spark.table("steward_decisions").toPandas()
data = labels.merge(pairs, on=["left_key", "right_key"])
data["y"] = (data["decision"] == "match").astype(int)
X = data[FEATURES].astype(float)
y = data["y"]
print(f"{len(data)} labelled pairs, {y.mean():.0%} matches")

# %% Train, evaluate and register
mlflow.set_experiment("goldenrecord-matcher")
with mlflow.start_run():
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.25, random_state=42, stratify=y)
    model = LogisticRegression(max_iter=1000).fit(X_train, y_train)
    pred = model.predict(X_test)
    mlflow.log_params({"features": ",".join(FEATURES), "n_labels": len(data)})
    mlflow.log_metrics({"precision": precision_score(y_test, pred), "recall": recall_score(y_test, pred)})
    mlflow.sklearn.log_model(model, "model", registered_model_name="goldenrecord-matcher")
