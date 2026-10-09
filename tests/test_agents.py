"""Agent tests on a small synthetic lakehouse, with no LLM and with a scripted fake LLM.

Includes the three "try to break it" scenarios: a wrong plain-English rule, a false merge, and 25K issues.
"""
import json
import re
from datetime import date

import pandas as pd
import pytest

from goldenrecord import synth
from goldenrecord.agents import ProfilerAgent, StewardAssistant
from goldenrecord.agents.base import AgentContext
from goldenrecord.agents.matcher import DECISIONS_SCHEMA
from goldenrecord.agents.orchestrator import run_pipeline
from goldenrecord.library import RuleLibrary
from goldenrecord.llm import LLMClient
from goldenrecord.matching import guarded_band
from goldenrecord.privacy import contains_raw_pii
from goldenrecord.reference import CITY_ALIASES, NAME_ABBREVIATIONS
from goldenrecord.store import Lakehouse

AS_OF = date(2026, 10, 9)


class FakeLLM(LLMClient):
    """Scripted stand-in: answers mapping questions from the reference data and calls every pair 'same'."""
    provider, model = "fake", "scripted"

    def _complete_json(self, system, prompt, schema):
        if schema is DECISIONS_SCHEMA:
            ids = [int(i) for i in re.findall(r"pair_id=(\d+)", prompt)]
            return {"decisions": [{"pair_id": i, "decision": "same", "confidence": 0.95,
                                   "explanation": "LLM: same company."} for i in ids]}
        props = schema["properties"]
        if "mappings" in props:
            raws = json.loads(prompt.split("Raw values: ")[1].replace("'", '"'))
            known = {**CITY_ALIASES, **NAME_ABBREVIATIONS, "RS": "INR"}
            return {"mappings": [{"raw": r, "canonical": known.get(r), "confidence": 0.95 if r in known else 0.2}
                                 for r in raws]}
        if "cause" in props:
            return {"cause": "fake cause", "action": "fake action"}
        if "recommendation" in props:
            return {"recommendation": "match", "rationale": "fake", "what_to_check": "tax ID"}
        return None


@pytest.fixture()
def lake(tmp_path):
    lk = Lakehouse(tmp_path / "lakehouse")
    synth.generate(n_vendors=250, n_invoices=2500, seed=5, raw_dir=lk.landing_dir, truth_dir=lk.truth_dir)
    return lk


def ctx_for(lake):
    return AgentContext(lake=lake, llm=None, run_id="t", as_of=AS_OF)


def test_rules_only_run_builds_every_layer_without_raw_pii(lake):
    s = run_pipeline(lake, as_of=AS_OF, use_env_llm=False)["summary"]
    assert s["llm"] == "none (rules only)" and s["llm_calls"] == 0
    for name in ("bronze_erp_a_vendors", "silver_vendor", "silver_match_pairs", "gold_vendor", "gold_vendor_xref",
                 "gold_spend_fact", "gold_merge_edges", "steward_patterns", "dq_scorecard", "agent_events",
                 "pii_vault", "run_history"):
        assert lake.exists(name), name
    vault = lake.read("pii_vault")
    for table in ("bronze_erp_a_vendors", "bronze_erp_b_vendors", "silver_vendor", "gold_vendor"):
        assert contains_raw_pii(lake.read(table), vault) == [], table
    assert lake.read("silver_vendor")["bank_account"].dropna().str.startswith("****").all()
    assert s["match_precision"] >= 0.95 and s["catch_rate"] >= 0.9


def test_llm_authors_mappings_once_then_reruns_are_deterministic_and_free(lake):
    first = run_pipeline(lake, llm=FakeLLM(), as_of=AS_OF)["summary"]
    assert first["values_sent_to_llm"] > 0
    assert any(i["item_id"] == "MAP:city:BANGALORE" for i in RuleLibrary(lake).active("value_mapping")) or \
        "BANGALORE" not in set(lake.read("bronze_erp_a_vendors")["ORT01"].str.upper())
    gold_first = lake.read("gold_vendor_xref").sort_values("record_key")["master_key"].tolist()
    second_llm = FakeLLM()
    second = run_pipeline(lake, llm=second_llm, as_of=AS_OF)["summary"]
    assert second["values_sent_to_llm"] == 0 and second["pairs_sent_to_llm"] == 0
    assert second_llm.stats.calls == 0
    assert lake.read("gold_vendor_xref").sort_values("record_key")["master_key"].tolist() == gold_first


def test_llm_cannot_merge_past_the_guardrail(lake):
    run_pipeline(lake, llm=FakeLLM(), as_of=AS_OF)
    pairs = lake.read("silver_match_pairs")
    reviewed = pairs[pairs["ai_decision"].notna()]
    assert not ((reviewed["band"] == "HIGH") & (reviewed["score"] < 0.80)).any()
    assert not ((reviewed["band"] == "HIGH") & (reviewed["tax_conflict"] == True)).any()  # noqa: E712


def test_guarded_band_rules():
    assert guarded_band(0.85, False, "same", 0.95) == "HIGH"
    assert guarded_band(0.75, False, "same", 0.95) == "MEDIUM"
    assert guarded_band(0.85, True, "same", 0.99) == "LOW"
    assert guarded_band(0.60, False, "different", 0.9) == "LOW"
    assert guarded_band(0.85, False, "same", 0.5) == "MEDIUM"
    assert guarded_band(0.95, False) == "HIGH"


def test_scenario_wrong_rule_is_previewed_blocked_shadowed_and_rolled_back(lake):
    run_pipeline(lake, as_of=AS_OF, use_env_llm=False)
    quarantined = len(lake.read("quarantine_invoice"))
    profiler, ctx = ProfilerAgent(), ctx_for(lake)
    # A mistaken rule: "1,000" instead of "1,000,000" would quarantine most invoices.
    preview = profiler.draft_rule(ctx, "Invoice amount must not exceed 1,000")
    assert preview["ok"] and preview["blocked"] and preview["preview"]["fail_rate"] > 0.05
    assert preview["preview"]["by_source"]  # impact broken down by ERP before anything is saved
    assert not profiler.draft_rule(ctx, "Invoice amount must not exceed 1,000", accept=True)["saved"]
    saved = profiler.draft_rule(ctx, "Invoice amount must not exceed 1,000", accept=True, override=True)
    assert saved["saved"] and saved["rule"]["mode"] == "shadow"
    after = run_pipeline(lake, as_of=AS_OF, use_env_llm=False)["summary"]
    assert after["shadow_rules"] == 1
    assert len(lake.read("quarantine_invoice")) == quarantined  # shadow rules quarantine nothing
    RuleLibrary(lake).retire("DQ:C01", by="steward", note="wrong threshold")
    assert run_pipeline(lake, as_of=AS_OF, use_env_llm=False)["summary"]["active_rules"] == 9
    # A correct rule within the limit can be promoted to enforce.
    good = profiler.draft_rule(ctx, "Invoice amount must not exceed 10,000,000", accept=True)
    assert good["saved"] and not good["blocked"]
    assert profiler.promote_rule(ctx, good["rule"]["id"], "steward")["rule"]["mode"] == "enforce"


def test_scenario_false_merge_is_detected_and_undone(lake):
    run_pipeline(lake, as_of=AS_OF, use_env_llm=False)
    pairs = lake.read("silver_match_pairs")
    wrong = pairs[pairs["tax_conflict"] == True].iloc[0]  # noqa: E712  two different companies
    st, ctx = StewardAssistant(), ctx_for(lake)
    st.record_decision(ctx, wrong["left_key"], wrong["right_key"], "match", "tired-steward")
    s = run_pipeline(lake, as_of=AS_OF, use_env_llm=False)["summary"]
    xref = lake.read("gold_vendor_xref").set_index("record_key")["master_key"]
    master = xref[wrong["left_key"]]
    assert master == xref[wrong["right_key"]]  # the false merge happened
    alerts = lake.read("gold_cluster_alerts")
    assert master in set(alerts["master_key"]) and s["suspect_golden_records"] >= 1  # and was detected
    why = st.explain(ctx, master)
    assert any(m["reason"] == "steward:tired-steward" for m in why["merges"])  # with its cause
    undo = st.unmerge(ctx, wrong["right_key"], "lead-steward", note="different tax IDs")
    assert undo["ok"] and undo["library_version"]
    run_pipeline(lake, as_of=AS_OF, use_env_llm=False)
    xref = lake.read("gold_vendor_xref").set_index("record_key")["master_key"]
    assert xref[wrong["left_key"]] != xref[wrong["right_key"]]  # undone, and it stays undone


def test_scenario_thousands_of_issues_become_a_short_pattern_queue(lake):
    s = run_pipeline(lake, as_of=AS_OF, use_env_llm=False)["summary"]
    assert s["issue_records"] > 500 and s["open_patterns"] < s["issue_records"] / 10
    patterns = lake.read("steward_patterns")
    fix = patterns[patterns["kind"] == "record_fix"].iloc[0]
    st, ctx = StewardAssistant(), ctx_for(lake)
    result = st.decide_pattern(ctx, fix["pattern_id"], "approve", "steward")
    assert result["ok"] and result["affected_records"] == fix["affected_records"]
    after = run_pipeline(lake, as_of=AS_OF, use_env_llm=False)["summary"]
    assert after["records_fixed"] >= int(fix["affected_records"]) * 0.9  # one click, hundreds of records
    fixed = lake.read("silver_invoice")
    assert set(fixed["fixed_by"].dropna()) == {json.loads(fix["proposed_item"])["item_id"]}  # with lineage
    assert fix["pattern_id"] not in set(lake.read("steward_patterns")["pattern_id"])


def test_sentinel_raises_alert_on_bad_batch(lake):
    run_pipeline(lake, as_of=AS_OF, use_env_llm=False)
    synth.inject_bad_batch(lake.landing_dir, n=800, truth_dir=lake.truth_dir)
    second = run_pipeline(lake, as_of=AS_OF, use_env_llm=False)
    assert "AL01" in second["summary"]["alerts"] and "AL06" in second["summary"]["alerts"]


def test_training_needs_enough_labels(lake, tmp_path):
    run_pipeline(lake, as_of=AS_OF, use_env_llm=False)
    pairs = lake.read("silver_match_pairs")
    truth = pd.read_csv(lake.truth_dir / "vendor_truth.csv", dtype=str)
    tid = dict(zip(truth["source_system"] + ":" + truth["source_vendor_id"], truth["true_vendor_id"]))
    sample = pairs.groupby("band").head(40)
    decisions = pd.DataFrame({"left_key": sample["left_key"], "right_key": sample["right_key"],
                              "decision": ["match" if tid[a] == tid[b] else "no_match"
                                           for a, b in zip(sample["left_key"], sample["right_key"])],
                              "reviewer": "t", "decided_at": pd.Timestamp("2026-10-09", tz="UTC")})
    from goldenrecord.learning import train_matcher
    uri = (tmp_path / "mlruns").as_uri()
    assert train_matcher(pairs, decisions, tracking_uri=uri)["ok"]
    assert not train_matcher(pairs, decisions.head(5), tracking_uri=uri)["ok"]
