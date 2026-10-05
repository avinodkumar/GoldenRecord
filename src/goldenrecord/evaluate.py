"""Score the pipeline against the seeded ground truth (numbers for the Proof slide)."""
from __future__ import annotations

from math import comb

import pandas as pd


def pairwise_match_metrics(xref: pd.DataFrame, truth: pd.DataFrame) -> dict:
    """Pairwise precision/recall of predicted clusters versus true vendors."""
    t = truth.assign(record_key=truth["source_system"] + ":" + truth["source_vendor_id"].astype(str))
    df = xref[["record_key", "master_key"]].merge(t[["record_key", "true_vendor_id"]], on="record_key")
    predicted = sum(comb(n, 2) for n in df.groupby("master_key").size())
    actual = sum(comb(n, 2) for n in df.groupby("true_vendor_id").size())
    correct = sum(comb(n, 2) for n in df.groupby(["master_key", "true_vendor_id"]).size())
    precision = correct / predicted if predicted else 1.0
    recall = correct / actual if actual else 1.0
    return {
        "match_precision": round(precision, 4),
        "match_recall": round(recall, 4),
        "golden_records": int(df["master_key"].nunique()),
        "true_vendors": int(df["true_vendor_id"].nunique()),
    }


def rule_catch_metrics(flags: pd.DataFrame, defects: pd.DataFrame, invoices: pd.DataFrame) -> dict:
    """Catch rate of seeded rule/anomaly defects and false-quarantine rate on clean invoices."""
    expected = defects[defects["expected_rule"].notna()][["record_key", "expected_rule", "defect_type"]]
    flagged = set(zip(flags["record_key"], flags["rule_id"]))
    expected = expected.assign(caught=[(k, r) in flagged for k, r in
                                       zip(expected["record_key"], expected["expected_rule"])])
    by_type = expected.groupby("defect_type")["caught"].mean().round(4).to_dict()

    inv_flagged = set(flags.loc[flags["entity"] == "invoice", "record_key"])
    defective_invoices = set(defects.loc[defects["entity"] == "invoice", "record_key"])
    clean = set(invoices["record_key"]) - defective_invoices
    false_flags = len(clean & inv_flagged)
    return {
        "catch_rate": round(float(expected["caught"].mean()), 4) if len(expected) else 1.0,
        "catch_rate_by_defect": by_type,
        "false_quarantine_rate": round(false_flags / len(clean), 4) if clean else 0.0,
    }
