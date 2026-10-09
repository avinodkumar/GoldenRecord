"""Steward assistant: turns thousands of issues into a short, ranked list of root-cause patterns.

A steward approves one pattern ("use the vendor's country currency for 812 ERP_B invoices") and the
proposed fix becomes a versioned rule-library item that applies to those records and every future one.
It also explains any golden record (which merges built it, and why) and undoes a false merge with a
cannot-link that future runs respect. Pair-level review is still there for drill-down.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

from ..learning import train_matcher
from ..library import RuleLibrary
from ..mappings import canonical_cities
from ..reference import VALID_CURRENCIES
from ..patterns import coverage, dq_patterns, mapping_patterns, match_patterns
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
    role = "Groups issues into root-cause patterns, applies bulk decisions, explains and undoes merges"

    # --- pattern triage (runs after the Gatekeeper) ----------------------------------------------
    def run(self, ctx: AgentContext) -> dict:
        lib = RuleLibrary(ctx.lake)
        s = ctx.state
        decided = ctx.lake.read("pattern_decisions")
        closed = set() if decided.empty else set(decided["pattern_id"])
        patterns = pd.concat([
            mapping_patterns(s.get("mapping_proposals", [])),
            dq_patterns(s["flags"], s["vendors"], s["invoices"], s["rules"], lib.acknowledged(), s["enforced_rules"]),
            match_patterns(s["review_queue"]),
        ], ignore_index=True)
        patterns = patterns[~patterns["pattern_id"].isin(closed)]
        patterns = patterns.sort_values("affected_records", ascending=False).reset_index(drop=True)
        patterns["run_id"] = ctx.run_id
        ctx.lake.write("steward_patterns", patterns)
        cov = coverage(patterns)
        issue_records = int(s["flags"]["record_key"].nunique()) + len(s["review_queue"])
        cov["issue_records"] = issue_records
        self.log(ctx, "patterns_built",
                 f"{issue_records:,} open issue records grouped into {cov['open_patterns']} patterns; "
                 f"top 10 cover {cov['top10_coverage']:.0%}", records=cov["open_patterns"])
        return cov

    def decide_pattern(self, ctx: AgentContext, pattern_id: str, decision: str, reviewer: str,
                       canonical: str | None = None, note: str = "") -> dict:
        if decision not in ("approve", "reject"):
            return {"ok": False, "error": "decision must be 'approve' or 'reject'"}
        patterns = ctx.lake.read("steward_patterns")
        hit = patterns[patterns["pattern_id"] == pattern_id]
        if hit.empty:
            return {"ok": False, "error": "pattern not found (already decided, or the run changed)"}
        p = hit.iloc[0].to_dict()
        item = json.loads(p["proposed_item"])
        version = None
        if decision == "approve":
            if item["kind"] == "value_mapping":  # single mapping: the steward may supply the canonical value
                item["definition"]["canonical"] = canonical or item["definition"].get("canonical")
                if not item["definition"]["canonical"]:
                    return {"ok": False, "error": "choose the canonical value for this mapping"}
                domain, chosen = item["definition"]["domain"], item["definition"]["canonical"]
                allowed = {"city": canonical_cities(), "currency": list(VALID_CURRENCIES)}.get(
                    domain, json.loads(p["options"] or "[]"))
                if chosen not in allowed:
                    return {"ok": False, "error": f"'{chosen}' is not a valid {domain}; choose from {allowed[:10]}"}
            item["source"] = "steward" if canonical else item.get("source", "steward")
            items = item["items"] if item["kind"] == "mapping_batch" else [item]
            version = RuleLibrary(ctx.lake).approve(items, approved_by=reviewer, note=note or p["title"])
        ctx.lake.append("pattern_decisions", pd.DataFrame([{
            "pattern_id": pattern_id, "item_id": item["item_id"], "kind": item["kind"], "decision": decision,
            "affected_records": int(p["affected_records"]), "reviewer": reviewer, "note": note,
            "library_version": version, "decided_at": datetime.now(timezone.utc)}]))
        self.log(ctx, f"pattern_{decision}d", f"{reviewer}: {p['title']} -> {item['item_id']} "
                 + (f"(library v{version})" if version else ""), records=int(p["affected_records"]))
        ctx.flush_events()
        return {"ok": True, "item_id": item["item_id"], "library_version": version,
                "affected_records": int(p["affected_records"]), "applies_from": "next pipeline run"}

    # --- golden record lineage and undo ----------------------------------------------------------
    def explain(self, ctx: AgentContext, master_key: str) -> dict:
        xref = ctx.lake.read("gold_vendor_xref")
        members = xref[xref["master_key"] == master_key]["record_key"].tolist()
        if not members:
            return {"ok": False, "error": "unknown master key"}
        edges = ctx.lake.read("gold_merge_edges")
        e = edges[edges["left_key"].isin(members) | edges["right_key"].isin(members)]
        alerts = ctx.lake.read("gold_cluster_alerts")
        a = alerts[alerts["master_key"] == master_key] if not alerts.empty else alerts
        return {"ok": True, "master_key": master_key, "members": members,
                "merges": e[["left_key", "right_key", "reason", "score"]].to_dict("records"),
                "suspect": None if a.empty else a.iloc[0]["issues"]}

    def unmerge(self, ctx: AgentContext, record_key: str, reviewer: str, note: str = "") -> dict:
        """Detach a record from its golden record: cannot-link it to every other member (versioned)."""
        xref = ctx.lake.read("gold_vendor_xref")
        row = xref[xref["record_key"] == record_key]
        if row.empty:
            return {"ok": False, "error": "unknown record"}
        master = row.iloc[0]["master_key"]
        others = xref[(xref["master_key"] == master) & (xref["record_key"] != record_key)]["record_key"].tolist()
        if not others:
            return {"ok": False, "error": "record is not merged with anything"}
        items = [{"item_id": f"SPLIT:{min(record_key, o)}|{max(record_key, o)}", "kind": "cannot_link",
                  "definition": {"left_key": record_key, "right_key": o}, "affected_records": 2} for o in others]
        version = RuleLibrary(ctx.lake).approve(items, approved_by=reviewer, note=note or f"unmerge from {master}")
        self.log(ctx, "unmerged", f"{reviewer}: {record_key} detached from {master} (library v{version})")
        ctx.flush_events()
        return {"ok": True, "master_key": master, "cannot_links": len(items), "library_version": version,
                "applies_from": "next pipeline run"}

    # --- pair-level drill-down -------------------------------------------------------------------
    def _pair(self, ctx: AgentContext, left_key: str, right_key: str) -> dict | None:
        pairs = ctx.lake.read("silver_match_pairs")
        hit = pairs[(pairs["left_key"] == left_key) & (pairs["right_key"] == right_key)]
        return None if hit.empty else hit.iloc[0].to_dict()

    def recommend(self, ctx: AgentContext, left_key: str, right_key: str) -> dict:
        pair = self._pair(ctx, left_key, right_key)
        if pair is None:
            return {"ok": False, "error": "pair not found"}
        vendors = ctx.lake.read("silver_vendor").set_index("record_key")
        drop = ["phone_token", "email_token", "bank_token"]
        left = vendors.loc[left_key].drop(drop, errors="ignore").to_dict()
        right = vendors.loc[right_key].drop(drop, errors="ignore").to_dict()
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
