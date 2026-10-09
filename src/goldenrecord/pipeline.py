"""Local end-to-end pipeline: raw -> Bronze -> Silver -> match -> Gold -> reports.

Mirrors the Fabric notebooks so logic can be developed and tested without a Fabric capacity.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from . import config
from .evaluate import pairwise_match_metrics, rule_catch_metrics
from .matching import candidate_pairs, cluster, score_pairs
from .rules import detect_amount_anomalies, load_rules, run_rules
from .standardize import standardize_invoices, standardize_vendors
from .survivorship import build_golden

BLOCKING_INVOICE_RULES = {"R05", "R06", "R07", "R08", "R09", "A01"}


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def ingest_bronze(raw_dir: Path = config.RAW_DIR, bronze_dir: Path = config.BRONZE_DIR) -> dict[str, pd.DataFrame]:
    bronze_dir.mkdir(parents=True, exist_ok=True)
    ingested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tables = {}
    for source in config.SOURCES:
        for entity in ("vendors", "invoices"):
            df = _read_csv(raw_dir / source / f"{entity}.csv")
            df["_source_system"] = source
            df["_ingested_at"] = ingested_at
            df.to_csv(bronze_dir / f"{source.lower()}_{entity}.csv", index=False)
            tables[f"{source}_{entity}"] = df
    return tables


def build_silver(bronze: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    drop = ["_source_system", "_ingested_at"]
    vendors = pd.concat([standardize_vendors(bronze[f"{s}_vendors"].drop(columns=drop), s)
                         for s in config.SOURCES], ignore_index=True)
    invoices = pd.concat([standardize_invoices(bronze[f"{s}_invoices"].drop(columns=drop), s)
                          for s in config.SOURCES], ignore_index=True)
    return vendors, invoices


def load_steward_decisions(labels_dir: Path = config.LABELS_DIR) -> pd.DataFrame:
    path = labels_dir / "steward_decisions.csv"
    if not path.exists():
        return pd.DataFrame(columns=["left_key", "right_key", "decision", "reviewer", "decided_at"])
    return _read_csv(path)


def resolve_matches(pairs: pd.DataFrame, decisions: pd.DataFrame) -> tuple[list[tuple[str, str]], pd.DataFrame]:
    """HIGH pairs merge unless a steward rejected them; MEDIUM pairs merge only when approved."""
    decided = {(r.left_key, r.right_key): r.decision for r in decisions.itertuples()}
    pairs = pairs.assign(steward_decision=[decided.get((a, b)) for a, b in zip(pairs["left_key"], pairs["right_key"])])
    merge = (((pairs["band"] == "HIGH") & (pairs["steward_decision"] != "no_match"))
             | ((pairs["band"] == "MEDIUM") & (pairs["steward_decision"] == "match")))
    matched = list(zip(pairs.loc[merge, "left_key"], pairs.loc[merge, "right_key"]))
    queue = pairs[(pairs["band"] == "MEDIUM") & pairs["steward_decision"].isna()]
    return matched, queue.drop(columns=["steward_decision"])


def _pass_share(keys: pd.Series, failing: set[str]) -> float:
    return round(float((~keys.isin(failing)).mean()), 4) if len(keys) else 1.0


def build_spend(invoices: pd.DataFrame, flags: pd.DataFrame, xref: pd.DataFrame,
                blocking: set[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (gold spend fact, quarantined invoices with their failed rules)."""
    blocking = BLOCKING_INVOICE_RULES if blocking is None else blocking
    blocked = flags[flags["rule_id"].isin(blocking)]
    reasons = blocked.groupby("record_key")["rule_id"].agg(lambda r: ",".join(sorted(set(r))))
    quarantine = invoices[invoices["record_key"].isin(reasons.index)].assign(
        failed_rules=lambda d: d["record_key"].map(reasons))
    clean = invoices[~invoices["record_key"].isin(reasons.index)]
    spend = clean.merge(xref[["record_key", "master_key"]].rename(columns={"record_key": "vendor_record_key"}),
                        on="vendor_record_key", how="inner")
    spend = spend.assign(amount_usd=(spend["amount"] * spend["currency"].map(config.FX_TO_USD)).round(2))
    cols = ["record_key", "master_key", "source_system", "invoice_no", "invoice_date", "currency", "amount",
            "amount_usd"]
    return spend[cols].reset_index(drop=True), quarantine.reset_index(drop=True)


def dq_scores(vendors, invoices, flags, gold_vendor, spend, rules, as_of) -> tuple[float, float]:
    """Share of records passing every rule in Silver (before) and in Gold (after)."""
    before = _pass_share(pd.concat([vendors["record_key"], invoices["record_key"]]), set(flags["record_key"]))
    vendor_rules = [r for r in rules if r["entity"] == "vendor"]
    gold_failures, _ = run_rules(gold_vendor.assign(record_key=gold_vendor["master_key"]),
                                 invoices.iloc[0:0], vendor_rules, as_of)
    after = _pass_share(pd.concat([gold_vendor["master_key"], spend["record_key"]]), set(gold_failures["record_key"]))
    return before, after


def run(as_of: date | None = None, data_dir: Path = config.DATA_DIR) -> dict:
    as_of = as_of or date.today()
    raw, bronze_dir, silver_dir = data_dir / "raw", data_dir / "bronze", data_dir / "silver"
    gold_dir, reports_dir, labels_dir = data_dir / "gold", data_dir / "reports", data_dir / "labels"
    for d in (silver_dir, gold_dir, reports_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Bronze and Silver
    bronze = ingest_bronze(raw, bronze_dir)
    vendors, invoices = build_silver(bronze)
    vendors.to_csv(silver_dir / "vendor.csv", index=False)
    invoices.to_csv(silver_dir / "invoice.csv", index=False)

    # Data-quality rules and anomaly check
    rules = load_rules()
    failures, scorecard = run_rules(vendors, invoices, rules, as_of)
    anomalies = detect_amount_anomalies(invoices)
    flags = pd.concat([failures, anomalies], ignore_index=True)
    flags.to_csv(silver_dir / "dq_failures.csv", index=False)
    scorecard.to_csv(reports_dir / "dq_scorecard.csv", index=False)

    # Matching with confidence bands
    pairs = score_pairs(vendors, candidate_pairs(vendors))
    pairs.to_csv(silver_dir / "match_pairs.csv", index=False)
    matched, review_queue = resolve_matches(pairs, load_steward_decisions(labels_dir))
    review_queue.to_csv(gold_dir / "review_queue.csv", index=False)

    # Gold: golden records with stable master keys
    xref_path = gold_dir / "vendor_xref.csv"
    previous_xref = _read_csv(xref_path) if xref_path.exists() else None
    clusters = cluster(vendors["record_key"], matched)
    gold_vendor, xref = build_golden(vendors, clusters, previous_xref)
    gold_vendor.to_csv(gold_dir / "gold_vendor.csv", index=False)
    xref.to_csv(xref_path, index=False)

    # Gold spend: only invoices that pass every blocking rule
    spend, quarantine = build_spend(invoices, flags, xref)
    quarantine.to_csv(gold_dir / "quarantine_invoice.csv", index=False)
    spend.to_csv(gold_dir / "gold_spend_fact.csv", index=False)

    # Data-quality score before (Silver) and after (Gold)
    before, after = dq_scores(vendors, invoices, flags, gold_vendor, spend, rules, as_of)

    metrics = {
        "as_of": as_of.isoformat(),
        "silver_vendor_records": len(vendors),
        "silver_invoice_records": len(invoices),
        "candidate_pairs": len(pairs),
        "pairs_by_band": pairs["band"].value_counts().to_dict(),
        "review_queue_size": len(review_queue),
        "golden_vendors": len(gold_vendor),
        "quarantined_invoices": len(quarantine),
        "gold_spend_invoices": len(spend),
        "gold_spend_usd": round(float(spend["amount_usd"].sum()), 2),
        "dq_score_before": before,
        "dq_score_after": after,
        "active_rules": len(rules),
    }

    truth_dir = data_dir / "truth"
    if (truth_dir / "vendor_truth.csv").exists():
        truth = _read_csv(truth_dir / "vendor_truth.csv")
        defects = _read_csv(truth_dir / "seeded_defects.csv").replace("", None)
        metrics.update(pairwise_match_metrics(xref, truth))
        metrics.update(rule_catch_metrics(flags, defects, invoices))

    with open(reports_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, default=str)
    return metrics


def simulate_review(n: int | None = None, data_dir: Path = config.DATA_DIR, reviewer: str = "simulated-steward") -> int:
    """Label review-queue pairs from ground truth, standing in for Power BI write-back during development."""
    queue = _read_csv(data_dir / "gold" / "review_queue.csv")
    truth = _read_csv(data_dir / "truth" / "vendor_truth.csv")
    true_id = dict(zip(truth["source_system"] + ":" + truth["source_vendor_id"], truth["true_vendor_id"]))
    if n is not None:
        queue = queue.head(n)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    labels = pd.DataFrame({
        "left_key": queue["left_key"], "right_key": queue["right_key"],
        "decision": ["match" if true_id[a] == true_id[b] else "no_match"
                     for a, b in zip(queue["left_key"], queue["right_key"])],
        "reviewer": reviewer, "decided_at": now,
    })
    labels_dir = data_dir / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)
    path = labels_dir / "steward_decisions.csv"
    existing = _read_csv(path) if path.exists() else labels.iloc[0:0]
    pd.concat([existing, labels], ignore_index=True).drop_duplicates(
        subset=["left_key", "right_key"], keep="last").to_csv(path, index=False)
    return len(labels)
