"""Matcher agent: candidate pairs, deterministic scores, and LLM review of the grey zone only.

Cost control, in order: deterministic scoring decides most pairs; library match rules (approved per
evidence pattern) decide whole groups; the pair cache answers anything judged before. Only genuinely new
grey-zone pairs reach the LLM (Fabric AI Functions in production), once.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

import pandas as pd

from ..config import GREY_ZONE
from ..library import RuleLibrary
from ..matching import candidate_pairs, evidence_signature, score_pairs
from .base import Agent, AgentContext

BATCH_SIZE = int(os.environ.get("LLM_PAIRS_PER_CALL", "10"))

DECISIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "pair_id": {"type": "integer"},
                    "decision": {"type": "string", "enum": ["same", "different", "unsure"]},
                    "confidence": {"type": "number"},
                    "explanation": {"type": "string"},
                },
                "required": ["pair_id", "decision", "confidence", "explanation"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["decisions"],
    "additionalProperties": False,
}

SYSTEM = (
    "You are a master-data steward deciding whether two vendor records from different ERP systems "
    "describe the same company. Consider legal-form variants (Ltd, Limited, Pvt Ltd), abbreviations, "
    "typos, acronyms and city aliases (Bangalore = Bengaluru). Different valid tax IDs usually mean "
    "different companies. Confidence is between 0 and 1. The explanation is one plain-English sentence "
    "for a data steward, based only on the evidence given."
)


def _describe(v: dict) -> str:
    return (f"name={v.get('vendor_name')}; city={v.get('city')}; country={v.get('country_iso2')}; "
            f"tax_id={v.get('tax_id')}; phone={v.get('phone')}; email_domain={v.get('email_domain')}")


def fingerprint(left: dict, right: dict) -> str:
    """Stable key for a pair's evidence: the same two descriptions are never sent to the LLM twice."""
    a, b = sorted([_describe(left), _describe(right)])
    return hashlib.sha1(f"{a}||{b}".encode()).hexdigest()


class MatcherAgent(Agent):
    name = "matcher"
    role = "Scores candidate duplicates deterministically; asks the LLM only about new, uncovered grey-zone pairs"

    def run(self, ctx: AgentContext) -> dict:
        vendors = ctx.state["vendors"]
        pairs = score_pairs(vendors, candidate_pairs(vendors))
        for col in ("ai_decision", "ai_confidence", "ai_explanation"):
            pairs[col] = None

        low, high = GREY_ZONE
        rules = RuleLibrary(ctx.lake).match_rules()
        lookup = vendors.astype(object).where(vendors.notna(), None).set_index("record_key").to_dict("index")
        grey = pairs[(pairs["score"] >= low) & (pairs["score"] < high)]
        sigs = pd.Series([evidence_signature(r) for r in grey.to_dict("records")], index=grey.index, dtype=object)
        grey = grey[~sigs.isin(rules)]  # a library match rule already decides these
        fps = pd.Series([fingerprint(lookup[a], lookup[b]) for a, b in zip(grey["left_key"], grey["right_key"])],
                        index=grey.index, dtype=object)

        cache = ctx.lake.read("llm_pair_cache")
        cached = {} if cache.empty else cache.drop_duplicates("fingerprint", keep="last").set_index("fingerprint")[
            ["decision", "confidence", "explanation"]].to_dict("index")
        from_cache = 0
        for idx, fp in fps.items():
            if fp in cached:
                c = cached[fp]
                pairs.loc[idx, ["ai_decision", "ai_confidence", "ai_explanation"]] = [
                    c["decision"], c["confidence"], c["explanation"]]
                from_cache += 1

        todo = grey[~fps.isin(cached)].sort_values("score", ascending=False)
        reviewed, new_cache = 0, []
        if ctx.llm and len(todo):
            for start in range(0, len(todo), BATCH_SIZE):
                if ctx.llm.stats.exhausted:
                    break
                batch = todo.iloc[start:start + BATCH_SIZE]
                lines = [f"pair_id={i}\n  A: {_describe(lookup[r.left_key])}\n  B: {_describe(lookup[r.right_key])}\n"
                         f"  rule evidence: {r.explanation} (score {r.score:.2f})"
                         for i, r in zip(batch.index, batch.itertuples())]
                result = ctx.llm.complete_json(SYSTEM, "Judge each pair:\n" + "\n".join(lines), DECISIONS_SCHEMA)
                for d in (result or {}).get("decisions", []):
                    if d["pair_id"] in batch.index:
                        conf = max(0.0, min(1.0, float(d["confidence"])))
                        pairs.loc[d["pair_id"], ["ai_decision", "ai_confidence", "ai_explanation"]] = [
                            d["decision"], conf, d["explanation"]]
                        new_cache.append({"fingerprint": fps[d["pair_id"]], "decision": d["decision"],
                                          "confidence": conf, "explanation": d["explanation"],
                                          "model": ctx.llm.model, "created_at": datetime.now(timezone.utc)})
                        reviewed += 1
        if new_cache:
            ctx.lake.append("llm_pair_cache", pd.DataFrame(new_cache))

        ctx.state["pairs"] = pairs
        detail = (f"{len(pairs)} candidate pairs; {len(sigs)} in the grey zone, {len(sigs) - len(grey)} decided by "
                  f"library match rules, {from_cache} from the decision cache, {reviewed} new LLM judgements")
        self.log(ctx, "pairs_scored", detail, reviewed > 0, len(pairs))
        return {"candidate_pairs": len(pairs), "grey_zone": len(sigs), "by_match_rules": len(sigs) - len(grey),
                "from_cache": from_cache, "llm_reviewed": reviewed}
