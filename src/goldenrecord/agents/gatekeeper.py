"""Gatekeeper agent: AI proposes, rules decide. Routes every pair, builds Gold and quarantines bad invoices."""
from __future__ import annotations

from ..matching import cluster, guarded_band
from ..pipeline import build_spend, dq_scores, resolve_matches
from ..survivorship import build_golden
from .base import Agent, AgentContext


class GatekeeperAgent(Agent):
    name = "gatekeeper"
    role = "Applies the guardrail to every match, then builds the golden records and governed spend"

    def run(self, ctx: AgentContext) -> dict:
        pairs = ctx.state["pairs"].copy()
        pairs["rule_band"] = pairs["band"]
        pairs["band"] = [guarded_band(s, tc, d, c) for s, tc, d, c in
                         zip(pairs["score"], pairs["tax_conflict"], pairs["ai_decision"], pairs["ai_confidence"])]
        pairs["decided_by"] = pairs["ai_decision"].map(lambda d: "rules+ai" if d else "rules")
        pairs["explanation"] = pairs["ai_explanation"].where(pairs["ai_explanation"].notna(), pairs["explanation"])
        overruled = int(((pairs["ai_decision"] == "same") & (pairs["band"] != "HIGH")).sum())
        promoted = int(((pairs["band"] == "HIGH") & (pairs["rule_band"] != "HIGH")).sum())
        ctx.lake.write("silver_match_pairs", pairs)

        decisions = ctx.lake.read("steward_decisions")
        if decisions.empty:
            decisions = decisions.reindex(columns=["left_key", "right_key", "decision"])
        else:  # latest decision per pair wins
            decisions = decisions.sort_values("decided_at").drop_duplicates(["left_key", "right_key"], keep="last")
        matched, review_queue = resolve_matches(pairs, decisions)

        vendors, invoices = ctx.state["vendors"], ctx.state["invoices"]
        previous_xref = ctx.lake.read("gold_vendor_xref") if ctx.lake.exists("gold_vendor_xref") else None
        gold_vendor, xref = build_golden(vendors, cluster(vendors["record_key"], matched), previous_xref)
        spend, quarantine = build_spend(invoices, ctx.state["flags"], xref)
        before, after = dq_scores(vendors, invoices, ctx.state["flags"], gold_vendor, spend,
                                  ctx.state["rules"], ctx.as_of)

        for name, df in {"gold_vendor": gold_vendor, "gold_vendor_xref": xref, "gold_spend_fact": spend,
                         "review_queue": review_queue, "quarantine_invoice": quarantine}.items():
            ctx.lake.write(name, df)
        ctx.state.update(gold_vendor=gold_vendor, xref=xref, spend=spend, quarantine=quarantine,
                         review_queue=review_queue, dq_before=before, dq_after=after, pairs=pairs)

        self.log(ctx, "gold_built",
                 f"{len(gold_vendor)} golden vendors from {len(vendors)} records; {len(review_queue)} pairs to review; "
                 f"{len(quarantine)} invoices quarantined; AI promoted {promoted} pairs, guardrail held back "
                 f"{overruled} AI 'same' calls", records=len(gold_vendor))
        return {"golden_vendors": len(gold_vendor), "review_queue": len(review_queue),
                "quarantined_invoices": len(quarantine), "ai_promoted": promoted, "guardrail_overruled": overruled,
                "dq_score_before": before, "dq_score_after": after}
