"""Steward assistant: recommends a decision for each review-queue pair and records the human's choice."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..learning import train_matcher
from .base import Agent, AgentContext

RECOMMENDATION_SCHEMA = {
    "type": "object",
    "properties": {
        "recommendation": {"type": "string", "enum": ["match", "no_match", "unsure"]},
        "rationale": {"type": "string"},
        "what_to_check": {"type": "string"},
    },
    "required": ["recommendation", "rationale", "what_to_check"],
    "additionalProperties": False,
}


class StewardAssistant(Agent):
    name = "steward"
    role = "Briefs the data steward on each uncertain pair and turns decisions into training labels"

    def _pair(self, ctx: AgentContext, left_key: str, right_key: str) -> dict | None:
        pairs = ctx.lake.read("silver_match_pairs")
        hit = pairs[(pairs["left_key"] == left_key) & (pairs["right_key"] == right_key)]
        return None if hit.empty else hit.iloc[0].to_dict()

    def recommend(self, ctx: AgentContext, left_key: str, right_key: str) -> dict:
        pair = self._pair(ctx, left_key, right_key)
        if pair is None:
            return {"ok": False, "error": "pair not found"}
        vendors = ctx.lake.read("silver_vendor").set_index("record_key")
        left, right = vendors.loc[left_key].to_dict(), vendors.loc[right_key].to_dict()

        if pair["tax_conflict"]:
            rec, why = "no_match", "The two records carry different valid tax IDs."
        elif pair["score"] >= 0.80:
            rec, why = "match", f"Strong evidence: {pair['explanation']}."
        else:
            rec, why = "unsure", f"Mixed evidence: {pair['explanation']}."
        check, used_llm = "Compare the tax ID and the bank account in the source ERPs.", False

        if ctx.llm:
            result = ctx.llm.complete_json(
                "You brief a data steward on whether two vendor records are the same company. Be concise and "
                "factual; never invent data. Say what the steward should verify before deciding.",
                f"Record A ({left_key}): {left}\nRecord B ({right_key}): {right}\n"
                f"Rule evidence: {pair['explanation']} (score {pair['score']:.2f}, band {pair['band']})",
                RECOMMENDATION_SCHEMA,
            )
            if result:
                rec, why, check, used_llm = result["recommendation"], result["rationale"], result["what_to_check"], True
        for side in (left, right):
            side.pop("bank_account", None)  # never shown in the review UI
        self.log(ctx, "recommended", f"{left_key} vs {right_key}: {rec}", used_llm)
        ctx.flush_events()
        return {"ok": True, "left": left, "right": right, "score": pair["score"], "band": pair["band"],
                "evidence": pair["explanation"], "recommendation": rec, "rationale": why,
                "what_to_check": check, "used_llm": used_llm}

    def record_decision(self, ctx: AgentContext, left_key: str, right_key: str, decision: str,
                        reviewer: str, note: str = "") -> dict:
        if decision not in ("match", "no_match"):
            return {"ok": False, "error": "decision must be 'match' or 'no_match'"}
        if self._pair(ctx, left_key, right_key) is None:
            return {"ok": False, "error": "pair not found"}
        row = {"left_key": left_key, "right_key": right_key, "decision": decision, "reviewer": reviewer,
               "note": note, "decided_at": datetime.now(timezone.utc)}
        ctx.lake.append("steward_decisions", pd.DataFrame([row]))
        self.log(ctx, "decision_recorded", f"{reviewer}: {left_key} vs {right_key} -> {decision}")
        ctx.flush_events()
        return {"ok": True, "saved": row}

    def train(self, ctx: AgentContext) -> dict:
        result = train_matcher(ctx.lake.read("silver_match_pairs"), ctx.lake.read("steward_decisions"))
        self.log(ctx, "model_trained" if result["ok"] else "training_skipped",
                 str({k: v for k, v in result.items() if k != "coefficients"}))
        ctx.flush_events()
        return result
