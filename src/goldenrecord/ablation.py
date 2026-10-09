"""Measured comparison on one seeded dataset: what native constraints alone give you versus GoldenRecord.

  A  Native constraints only   MLV CONSTRAINT ... ON MISMATCH DROP with the same nine rules: bad rows are
                               dropped and counted; no reasons per row, no repair, no entity resolution.
  B  GoldenRecord, rules only  quarantine with reasons, deterministic matching and survivorship, no steward.
  C  GoldenRecord + stewards   B plus one round of pattern-level steward approvals (simulated, see note).
  D  LLM on every row          cost profile only: calls needed and determinism. Accuracy is not claimed here;
                               it needs a live Fabric AI Functions run.

Run: python -m goldenrecord ablation
"""
from __future__ import annotations

import json
import shutil
from datetime import date
from math import comb
from pathlib import Path

import pandas as pd

from . import synth
from .agents import StewardAssistant
from .agents.base import AgentContext
from .agents.orchestrator import run_pipeline
from .reference import CITY_ALIASES
from .store import Lakehouse

AS_OF = date(2026, 10, 9)


def _resolution(xref: pd.DataFrame, truth: pd.DataFrame) -> dict:
    t = truth.assign(record_key=truth["source_system"] + ":" + truth["source_vendor_id"])
    df = xref[["record_key", "master_key"]].merge(t[["record_key", "true_vendor_id"]], on="record_key")
    pure = df.groupby("master_key")["true_vendor_id"].nunique() == 1
    complete = df.groupby("true_vendor_id")["master_key"].nunique() == 1
    exact = {tv for tv, ok in complete.items() if ok and pure[df[df["true_vendor_id"] == tv]["master_key"].iloc[0]]}
    predicted = sum(comb(n, 2) for n in df.groupby("master_key").size())
    actual = sum(comb(n, 2) for n in df.groupby("true_vendor_id").size())
    correct = sum(comb(n, 2) for n in df.groupby(["master_key", "true_vendor_id"]).size())
    multi = df.groupby("true_vendor_id").size()
    multi = set(multi[multi > 1].index)
    return {"vendors_exact": len(exact), "true_vendors": df["true_vendor_id"].nunique(),
            "multi_record_vendors": len(multi), "multi_record_vendors_resolved": len(exact & multi),
            "pair_precision": round(correct / predicted, 4) if predicted else 1.0,
            "pair_recall": round(correct / actual, 4) if actual else 1.0, "_exact": exact, "_map": df}


def _spend_on_resolved(lake: Lakehouse, res: dict) -> float:
    spend = lake.read("gold_spend_fact")
    vendor_of = dict(zip(res["_map"]["record_key"], res["_map"]["true_vendor_id"]))
    inv = lake.read("silver_invoice").drop_duplicates("record_key").set_index("record_key")["vendor_record_key"]
    tv = spend["record_key"].map(inv).map(vendor_of)
    return round(float(spend.loc[tv.isin(res["_exact"]), "amount_usd"].sum() / spend["amount_usd"].sum()), 4)


def run_ablation(workdir: Path, n_vendors: int = 3000, n_invoices: int = 45000, seed: int = 42) -> dict:
    workdir = Path(workdir)
    shutil.rmtree(workdir, ignore_errors=True)
    lake = Lakehouse(workdir / "lakehouse")
    synth.generate(n_vendors, n_invoices, seed, raw_dir=lake.landing_dir, truth_dir=lake.truth_dir)
    truth = pd.read_csv(lake.truth_dir / "vendor_truth.csv", dtype=str)

    b = run_pipeline(lake, as_of=AS_OF, use_env_llm=False)["summary"]
    vendors, invoices = lake.read("silver_vendor"), lake.read("silver_invoice")
    flags = lake.read("silver_dq_failures")
    enforced = flags[flags["mode"] == "enforce"]
    res_b = _resolution(lake.read("gold_vendor_xref"), truth)
    spend_b = _spend_on_resolved(lake, res_b)
    patterns = lake.read("steward_patterns")
    quarantined_b = int(lake.read("quarantine_invoice")["record_key"].nunique())

    # A: native constraints only. Same rules; failing invoices dropped; every source vendor ID stays separate.
    invoice_rules = {"R05", "R06", "R07", "R08", "R09", "A01"}
    dropped = enforced[enforced["rule_id"].isin(invoice_rules)]["record_key"].nunique()
    xref_a = vendors[["record_key"]].assign(master_key=vendors["record_key"])
    res_a = _resolution(xref_a, truth)
    a = {"issues_detected": int(enforced["record_key"].nunique()), "per_record_reasons": 0,
         "records_repaired": 0, "golden_vendors": len(vendors), "steward_decisions": 0,
         "steward_view": f"{enforced['rule_id'].nunique()} constraint counters ({dropped:,} invoices dropped)"}

    # C: one round of pattern decisions. City aliases are chosen from reference data, as a steward would.
    st = StewardAssistant()
    ctx = AgentContext(lake=lake, llm=None, run_id="ablation-steward", as_of=AS_OF)
    decisions = 0
    for p in patterns.itertuples():
        canonical = None
        if p.kind == "value_mapping" and p.needs_input:
            canonical = CITY_ALIASES.get(p.signature.split(":", 1)[1]) if p.signature.startswith("city:") else None
            if canonical is None:
                continue
        decisions += st.decide_pattern(ctx, p.pattern_id, "approve", "ablation-steward", canonical=canonical)["ok"]
    c = run_pipeline(lake, as_of=AS_OF, use_env_llm=False)["summary"]
    res_c = _resolution(lake.read("gold_vendor_xref"), truth)
    quarantined_c = int(lake.read("quarantine_invoice")["record_key"].nunique())
    spend_c = _spend_on_resolved(lake, res_c)
    rerun = run_pipeline(lake, as_of=AS_OF, use_env_llm=False)["summary"]
    deterministic = rerun["golden_vendors"] == c["golden_vendors"] and rerun["quarantined_invoices"] == c[
        "quarantined_invoices"]

    candidate_pairs = int(len(lake.read("silver_match_pairs")))
    rows = [
        {"approach": "A. Native MLV constraints only", **{k: v for k, v in a.items()},
         "vendors_resolved_exactly": res_a["vendors_exact"], "duplicate_vendors_merged": res_a["multi_record_vendors_resolved"],
         "pair_recall": 0.0, "pair_precision": None, "gold_spend_on_correct_vendor": None,
         "llm_calls": 0, "deterministic": True},
        {"approach": "B. GoldenRecord, rules only", "issues_detected": b["issue_records"],
         "per_record_reasons": quarantined_b, "records_repaired": b["records_fixed"],
         "golden_vendors": b["golden_vendors"], "steward_decisions": 0,
         "steward_view": f"{b['open_patterns']} root-cause patterns (top 10 = {b['top10_coverage']:.0%} of issues)",
         "vendors_resolved_exactly": res_b["vendors_exact"], "duplicate_vendors_merged": res_b["multi_record_vendors_resolved"],
         "pair_recall": res_b["pair_recall"], "pair_precision": res_b["pair_precision"],
         "gold_spend_on_correct_vendor": spend_b, "llm_calls": 0, "deterministic": True},
        {"approach": "C. GoldenRecord + one round of pattern approvals", "issues_detected": c["issue_records"],
         "per_record_reasons": quarantined_c, "records_repaired": c["records_fixed"],
         "golden_vendors": c["golden_vendors"], "steward_decisions": decisions,
         "steward_view": f"{c['open_patterns']} patterns left; rule library v{c['library_version']}",
         "vendors_resolved_exactly": res_c["vendors_exact"], "duplicate_vendors_merged": res_c["multi_record_vendors_resolved"],
         "pair_recall": res_c["pair_recall"], "pair_precision": res_c["pair_precision"],
         "gold_spend_on_correct_vendor": spend_c, "llm_calls": 0, "deterministic": deterministic},
        {"approach": "D. LLM on every row (cost profile)", "issues_detected": None, "per_record_reasons": None,
         "records_repaired": None, "golden_vendors": None, "steward_decisions": None,
         "steward_view": "one LLM verdict per record and pair",
         "vendors_resolved_exactly": None, "duplicate_vendors_merged": None, "pair_recall": None,
         "pair_precision": None, "gold_spend_on_correct_vendor": None,
         "llm_calls": len(vendors) + len(invoices) + candidate_pairs, "deterministic": False},
    ]
    table = pd.DataFrame(rows)
    meta = {"dataset": f"seed {seed}: {len(vendors):,} vendor + {len(invoices):,} invoice records, "
                       f"{res_b['true_vendors']:,} true vendors ({res_b['multi_record_vendors']:,} held in 2+ records)",
            "note": "C simulates a steward approving each proposed pattern once; for the 11 unknown city aliases "
                    "the steward picks the correct city. D's accuracy is not measured without a live LLM."}
    out = workdir / "ablation.json"
    out.write_text(json.dumps({"meta": meta, "rows": rows}, indent=2, default=str), encoding="utf-8")
    return {"meta": meta, "table": table}
