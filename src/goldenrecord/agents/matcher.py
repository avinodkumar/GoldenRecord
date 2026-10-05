"""Matcher agent: candidate pairs, deterministic scores, and LLM review of the grey zone.

Locally this plays the role of Fabric AI Functions (ai.similarity / ai.classify / ai.generate_response):
for each grey-zone pair the LLM returns a decision, a confidence and a one-sentence explanation.
"""
from __future__ import annotations

import os

import pandas as pd

from ..config import GREY_ZONE
from ..matching import candidate_pairs, score_pairs
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


class MatcherAgent(Agent):
    name = "matcher"
    role = "Finds candidate duplicate vendors and asks the LLM to judge the uncertain ones"

    def run(self, ctx: AgentContext) -> dict:
        vendors = ctx.state["vendors"]
        pairs = score_pairs(vendors, candidate_pairs(vendors))
        pairs["ai_decision"] = None
        pairs["ai_confidence"] = None
        pairs["ai_explanation"] = None

        low, high = GREY_ZONE
        grey = pairs[(pairs["score"] >= low) & (pairs["score"] < high)]
        # Pairs nearest the merge threshold matter most, so they get the LLM budget first.
        grey = grey.sort_values("score", ascending=False)
        reviewed = 0
        if ctx.llm and len(grey):
            lookup = vendors.astype(object).where(vendors.notna(), None).set_index("record_key").to_dict("index")
            for start in range(0, len(grey), BATCH_SIZE):
                if ctx.llm.stats.exhausted:
                    break
                batch = grey.iloc[start:start + BATCH_SIZE]
                lines = [f"pair_id={i}\n  A: {_describe(lookup[r.left_key])}\n  B: {_describe(lookup[r.right_key])}\n"
                         f"  rule evidence: {r.explanation} (score {r.score:.2f})"
                         for i, r in zip(batch.index, batch.itertuples())]
                result = ctx.llm.complete_json(SYSTEM, "Judge each pair:\n" + "\n".join(lines), DECISIONS_SCHEMA)
                for d in (result or {}).get("decisions", []):
                    if d["pair_id"] in batch.index:
                        pairs.loc[d["pair_id"], ["ai_decision", "ai_confidence", "ai_explanation"]] = [
                            d["decision"], max(0.0, min(1.0, float(d["confidence"]))), d["explanation"]]
                        reviewed += 1

        ctx.state["pairs"] = pairs
        detail = (f"{len(pairs)} candidate pairs; {len(grey)} in the grey zone; "
                  f"{reviewed} reviewed by {'LLM ' + ctx.llm.model if ctx.llm else 'rules only (no LLM configured)'}")
        self.log(ctx, "pairs_scored", detail, reviewed > 0, len(pairs))
        return {"candidate_pairs": len(pairs), "grey_zone": len(grey), "llm_reviewed": reviewed}
