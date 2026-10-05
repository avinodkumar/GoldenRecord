"""Deterministic data-quality rules and the invoice anomaly check.

Rules are declared in config/dq_rules.yaml and mirrored in Microsoft Purview.
The same rules re-validate every AI-proposed merge, so the LLM never has the last word.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import yaml

from .config import ANOMALY_MIN_HISTORY, ANOMALY_MULTIPLIER, CONFIG_DIR


def load_rules(path: Path = CONFIG_DIR / "dq_rules.yaml") -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["rules"]


def _failures(rule: dict, df: pd.DataFrame, as_of: date, vendor_keys: set[str]) -> pd.Series:
    """Boolean Series, True where the record fails the rule."""
    col = df[rule["column"]]
    kind = rule["type"]
    if kind == "not_null":
        return col.isna()
    if kind == "regex":
        matches = col.fillna("").str.match(rule["pattern"])
        return ~matches & ~(col.isna() & rule.get("skip_null", False))
    if kind == "positive":
        return col.isna() | (col.fillna(0) <= 0)
    if kind == "date_not_future":
        return col.map(lambda d: d is None or pd.isna(d) or d > as_of)
    if kind == "range":
        values = pd.to_numeric(col, errors="coerce")
        failed = values.isna()
        if rule.get("min") is not None:
            failed |= values < rule["min"]
        if rule.get("max") is not None:
            failed |= values > rule["max"]
        return failed
    if kind == "allowed_values":
        return ~col.isin(rule["values"])
    if kind == "reference":
        return ~col.isin(vendor_keys)
    if kind == "unique":
        return col.duplicated(keep=False)
    raise ValueError(f"unknown rule type {kind!r} in {rule['id']}")


def run_rules(vendors: pd.DataFrame, invoices: pd.DataFrame, rules: list[dict],
              as_of: date | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (failures, summary). failures has one row per (rule, failing record)."""
    as_of = as_of or date.today()
    vendor_keys = set(vendors["record_key"])
    frames = {"vendor": vendors, "invoice": invoices}
    failures, summary = [], []
    for rule in rules:
        df = frames[rule["entity"]]
        failed = _failures(rule, df, as_of, vendor_keys)
        keys = df.loc[failed, "record_key"].unique()
        failures.append(pd.DataFrame({"rule_id": rule["id"], "entity": rule["entity"], "record_key": keys}))
        evaluated = len(df)
        n_failed = int(failed.sum())
        summary.append({"rule_id": rule["id"], "name": rule["name"], "entity": rule["entity"],
                        "dimension": rule["dimension"], "severity": rule["severity"],
                        "evaluated": evaluated, "failed": n_failed,
                        "pass_rate": round(1 - n_failed / evaluated, 4) if evaluated else 1.0})
    return pd.concat(failures, ignore_index=True), pd.DataFrame(summary)


def detect_amount_anomalies(invoices: pd.DataFrame) -> pd.DataFrame:
    """Flag invoices far above their vendor's median amount (rule A01)."""
    valid = invoices[invoices["amount"].notna() & (invoices["amount"] > 0)]
    stats = valid.groupby("vendor_record_key")["amount"].agg(["median", "count"])
    joined = valid.join(stats, on="vendor_record_key")
    flagged = joined[(joined["count"] >= ANOMALY_MIN_HISTORY)
                     & (joined["amount"] > ANOMALY_MULTIPLIER * joined["median"])]
    return pd.DataFrame({"rule_id": "A01", "entity": "invoice", "record_key": flagged["record_key"].unique()})
