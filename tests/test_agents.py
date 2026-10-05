"""Agent tests on a small synthetic lakehouse, with no LLM and with a scripted fake LLM."""
import re
from datetime import date

import pandas as pd
import pytest

from goldenrecord import synth
from goldenrecord.agents import ProfilerAgent, StewardAssistant
from goldenrecord.agents.base import AgentContext
from goldenrecord.agents.matcher import DECISIONS_SCHEMA
from goldenrecord.agents.orchestrator import run_pipeline
from goldenrecord.llm import LLMClient
from goldenrecord.matching import guarded_band
from goldenrecord.store import Lakehouse

AS_OF = date(2026, 10, 4)


class FakeLLM(LLMClient):
    """Says 'same' with high confidence for every pair; returns fixed text for other schemas."""
    provider, model = "fake", "scripted"

    def _complete_json(self, system, prompt, schema):
        if schema is DECISIONS_SCHEMA:
            ids = [int(i) for i in re.findall(r"pair_id=(\d+)", prompt)]
            return {"decisions": [{"pair_id": i, "decision": "same", "confidence": 0.95,
                                   "explanation": "LLM: same company."} for i in ids]}
        props = schema["properties"]
        if "findings" in props:
            return {"findings": ["fake finding"]}
        if "summary" in props:
            return {"summary": "fake summary"}
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


def test_rules_only_run_builds_every_layer(lake):
    result = run_pipeline(lake, as_of=AS_OF, use_env_llm=False)
    s = result["summary"]
    assert s["llm"] == "none (rules only)" and s["llm_calls"] == 0
    for name in ("bronze_erp_a_vendors", "silver_vendor", "silver_match_pairs", "gold_vendor", "gold_vendor_xref",
                 "gold_spend_fact", "review_queue", "dq_scorecard", "dq_run_metrics", "agent_events", "run_history"):
        assert lake.exists(name), name
    assert s["match_precision"] >= 0.95 and s["catch_rate"] >= 0.9
    assert set(lake.read("agent_events")["agent"]) >= {"profiler", "quality", "matcher", "gatekeeper", "sentinel"}


def test_llm_cannot_merge_past_the_guardrail(lake):
    llm = FakeLLM()
    result = run_pipeline(lake, llm=llm, as_of=AS_OF)
    pairs = lake.read("silver_match_pairs")
    reviewed = pairs[pairs["ai_decision"].notna()]
    assert len(reviewed) > 0 and llm.stats.calls > 0
    # The fake LLM says "same" for everything, yet a low score or tax conflict never reaches HIGH.
    assert not ((reviewed["band"] == "HIGH") & (reviewed["score"] < 0.80)).any()
    assert not ((reviewed["band"] == "HIGH") & (reviewed["tax_conflict"] == True)).any()  # noqa: E712
    assert result["agents"]["gatekeeper"]["guardrail_overruled"] >= 0


def test_guarded_band_rules():
    assert guarded_band(0.85, False, "same", 0.95) == "HIGH"
    assert guarded_band(0.75, False, "same", 0.95) == "MEDIUM"
    assert guarded_band(0.85, True, "same", 0.99) == "LOW"
    assert guarded_band(0.60, False, "different", 0.9) == "LOW"
    assert guarded_band(0.85, False, "same", 0.5) == "MEDIUM"
    assert guarded_band(0.95, False) == "HIGH"


def test_sentinel_raises_alert_on_bad_batch(lake):
    run_pipeline(lake, as_of=AS_OF, use_env_llm=False)
    synth.inject_bad_batch(lake.landing_dir, n=800, truth_dir=lake.truth_dir)
    second = run_pipeline(lake, as_of=AS_OF, use_env_llm=False)
    assert "AL01" in second["summary"]["alerts"]
    assert not lake.read("alerts").empty


def test_steward_decision_merges_on_next_run_and_master_keys_hold(lake):
    first = run_pipeline(lake, as_of=AS_OF, use_env_llm=False)
    keys_before = set(lake.read("gold_vendor_xref")["master_key"])
    queue = lake.read("review_queue")
    assert len(queue) > 0
    ctx = AgentContext(lake=lake, llm=None, run_id="t", as_of=AS_OF)
    steward = StewardAssistant()
    pair = queue.iloc[0]
    rec = steward.recommend(ctx, pair["left_key"], pair["right_key"])
    assert rec["ok"] and "bank_account" not in rec["left"]
    assert steward.record_decision(ctx, pair["left_key"], pair["right_key"], "match", "tester")["ok"]
    second = run_pipeline(lake, as_of=AS_OF, use_env_llm=False)
    assert second["summary"]["review_queue"] == first["summary"]["review_queue"] - 1
    xref = lake.read("gold_vendor_xref").set_index("record_key")["master_key"]
    assert xref[pair["left_key"]] == xref[pair["right_key"]]
    assert len(set(xref) - keys_before) == 0  # merging reuses existing keys; none invented


def test_profiler_drafts_validates_and_saves_rule(lake):
    run_pipeline(lake, as_of=AS_OF, use_env_llm=False)
    ctx = AgentContext(lake=lake, llm=None, run_id="t", as_of=AS_OF)
    profiler = ProfilerAgent()
    draft = profiler.draft_rule(ctx, "Vendor email must not be empty")
    assert draft["ok"] and draft["rule"]["type"] == "not_null" and draft["rule"]["column"] == "email"
    assert not lake.exists("dq_rules_custom")
    bad = profiler.draft_rule(ctx, "The moon must be blue")
    assert not bad["ok"]
    saved = profiler.draft_rule(ctx, "Invoice amount must not exceed 1,000,000", accept=True)
    assert saved["ok"] and saved["rule"]["type"] == "range" and saved["rule"]["max"] == 1_000_000
    result = run_pipeline(lake, as_of=AS_OF, use_env_llm=False)
    assert result["summary"]["active_rules"] == 10
    assert "C01" in set(lake.read("dq_scorecard")["rule_id"])


def test_training_needs_enough_labels(lake, tmp_path):
    run_pipeline(lake, as_of=AS_OF, use_env_llm=False)
    pairs = lake.read("silver_match_pairs")
    truth = pd.read_csv(lake.truth_dir / "vendor_truth.csv", dtype=str)
    tid = dict(zip(truth["source_system"] + ":" + truth["source_vendor_id"], truth["true_vendor_id"]))
    sample = pairs.groupby("band").head(40)
    decisions = pd.DataFrame({"left_key": sample["left_key"], "right_key": sample["right_key"],
                              "decision": ["match" if tid[a] == tid[b] else "no_match"
                                           for a, b in zip(sample["left_key"], sample["right_key"])],
                              "reviewer": "t", "decided_at": pd.Timestamp("2026-10-04", tz="UTC")})
    from goldenrecord.learning import train_matcher
    result = train_matcher(pairs, decisions, tracking_uri=(tmp_path / "mlruns").as_uri())
    assert result["ok"] and result["precision"] >= 0.8
    assert not train_matcher(pairs, decisions.head(5), tracking_uri=(tmp_path / "mlruns").as_uri())["ok"]
    # One-sided steward labels (all "match") still train, thanks to the automatic HIGH/LOW labels.
    one_sided = decisions.assign(decision="match").head(25)
    assert train_matcher(pairs, one_sided, tracking_uri=(tmp_path / "mlruns").as_uri())["ok"]
