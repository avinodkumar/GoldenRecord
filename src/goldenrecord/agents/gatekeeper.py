"""Gatekeeper agent: AI proposes, rules decide. Decides every merge, builds Gold, and checks its own work.

Merge precedence (strongest first): a steward's cannot-link or pair decision, a library match rule for
the pair's evidence pattern, then the guarded band (HIGH merges). Every accepted merge is written to
gold_merge_edges with its reason, so any golden record can be explained and any merge undone.
After clustering, each golden record is checked for signs of a false merge (two valid tax IDs, two
countries, two bank accounts, dissimilar names) and flagged in gold_cluster_alerts.
"""
from __future__ import annotations

import pandas as pd

from ..library import RuleLibrary
from ..matching import cluster_with_constraints, evidence_signature, guarded_band, name_similarity
from ..pipeline import build_spend, dq_scores
from ..survivorship import build_golden
from .base import Agent, AgentContext


def consistency_alerts(vendors: pd.DataFrame, xref: pd.DataFrame, run_id: str) -> pd.DataFrame:
    """Golden records that look like two different companies merged together."""
    v = vendors.merge(xref[["record_key", "master_key"]], on="record_key")
    v = v[v.groupby("master_key")["record_key"].transform("size") > 1]
    rows = []
    for key, g in v.groupby("master_key"):
        issues = []
        taxes = {t for t in g["tax_id"].dropna() if isinstance(t, str) and len(t) == 12}
        if len(taxes) > 1:
            issues.append(f"{len(taxes)} different valid tax IDs")
        if g["country_iso2"].dropna().nunique() > 1:
            issues.append("members in different countries")
        if "bank_token" in g and g["bank_token"].dropna().nunique() > 1:
            issues.append("different bank accounts")
        names = g["vendor_name_norm"].dropna().unique().tolist()
        worst = min((name_similarity(a, b) for i, a in enumerate(names) for b in names[i + 1:]), default=1.0)
        if worst < 0.6:
            issues.append(f"dissimilar names (similarity {worst:.2f})")
        if issues:
            rows.append({"master_key": key, "issues": "; ".join(issues), "members": ",".join(g["record_key"]),
                         "member_count": len(g), "run_id": run_id})
    return pd.DataFrame(rows, columns=["master_key", "issues", "members", "member_count", "run_id"])


class GatekeeperAgent(Agent):
    name = "gatekeeper"
    role = "Decides every merge with the guardrail and the rule library, builds Gold, and flags suspect merges"

    def run(self, ctx: AgentContext) -> dict:
        lib = RuleLibrary(ctx.lake)
        pairs = ctx.state["pairs"].copy()
        pairs["rule_band"] = pairs["band"]
        pairs["band"] = [guarded_band(s, tc, d, c) for s, tc, d, c in
                         zip(pairs["score"], pairs["tax_conflict"], pairs["ai_decision"], pairs["ai_confidence"])]
        pairs["explanation"] = pairs["ai_explanation"].where(pairs["ai_explanation"].notna(), pairs["explanation"])
        pairs["signature"] = [evidence_signature(r) for r in pairs.to_dict("records")]

        decisions = ctx.lake.read("steward_decisions")
        decided = {} if decisions.empty else {
            (r.left_key, r.right_key): (r.decision, f"steward:{r.reviewer}") for r in
            decisions.sort_values("decided_at").drop_duplicates(["left_key", "right_key"], keep="last").itertuples()}
        match_rules = lib.match_rules()

        merge, decided_by = [], []
        for r in pairs.itertuples():
            if (r.left_key, r.right_key) in decided:
                d, who = decided[(r.left_key, r.right_key)]
                merge.append(d == "match"); decided_by.append(who)
            elif r.band == "MEDIUM" and r.signature in match_rules:
                d, item = match_rules[r.signature]
                merge.append(d == "match"); decided_by.append(item)
            else:
                merge.append(r.band == "HIGH"); decided_by.append("rules+ai" if r.ai_decision else "rules")
        pairs["merge"], pairs["decided_by"] = merge, decided_by
        promoted = int(((pairs["band"] == "HIGH") & (pairs["rule_band"] != "HIGH")).sum())
        overruled = int(((pairs["ai_decision"] == "same") & (pairs["band"] != "HIGH")).sum())
        ctx.lake.write("silver_match_pairs", pairs)

        edges = [(r.left_key, r.right_key, r.decided_by, r.score) for r in pairs[pairs["merge"]].itertuples()]
        cannot = lib.cannot_links()
        vendors, invoices = ctx.state["vendors"], ctx.state["invoices"]
        clusters, accepted, blocked = cluster_with_constraints(vendors["record_key"], edges,
                                                               [(a, b) for a, b, _ in cannot])
        previous_xref = ctx.lake.read("gold_vendor_xref") if ctx.lake.exists("gold_vendor_xref") else None
        gold_vendor, xref = build_golden(vendors, clusters, previous_xref)
        blocking = {r["id"] for r in ctx.state["rules"]
                    if r["entity"] == "invoice" and r.get("mode", "enforce") == "enforce"} | {"A01"}
        spend, quarantine = build_spend(invoices, ctx.state["flags"], xref, blocking=blocking)
        before, after = dq_scores(vendors, invoices, ctx.state["flags"], gold_vendor, spend,
                                  [r for r in ctx.state["rules"] if r.get("mode", "enforce") == "enforce"], ctx.as_of)

        open_pairs = pairs[(pairs["band"] == "MEDIUM") & ~pairs["decided_by"].str.startswith(("steward:", "MATCH:"))]
        merge_edges = pd.DataFrame(accepted, columns=["left_key", "right_key", "reason", "score"]).assign(
            run_id=ctx.run_id, library_version=lib.version())
        alerts = consistency_alerts(vendors, xref, ctx.run_id)
        for name, df in {"gold_vendor": gold_vendor, "gold_vendor_xref": xref, "gold_spend_fact": spend,
                         "review_queue": open_pairs, "quarantine_invoice": quarantine,
                         "gold_merge_edges": merge_edges, "gold_cluster_alerts": alerts}.items():
            ctx.lake.write(name, df)
        ctx.lake.append("gold_vendor_xref_history", xref.assign(run_id=ctx.run_id, library_version=lib.version()))
        ctx.state.update(gold_vendor=gold_vendor, xref=xref, spend=spend, quarantine=quarantine, pairs=pairs,
                         review_queue=open_pairs, dq_before=before, dq_after=after, cluster_alerts=alerts)

        self.log(ctx, "gold_built",
                 f"{len(gold_vendor)} golden vendors from {len(vendors)} records (library v{lib.version()}); "
                 f"{len(open_pairs)} pairs open; {len(blocked)} merges blocked by cannot-links; "
                 f"{len(alerts)} suspect golden records; {len(quarantine)} invoices quarantined; "
                 f"AI promoted {promoted}, guardrail held back {overruled}", records=len(gold_vendor))
        return {"golden_vendors": len(gold_vendor), "review_queue": len(open_pairs),
                "quarantined_invoices": len(quarantine), "ai_promoted": promoted, "guardrail_overruled": overruled,
                "blocked_by_cannot_link": len(blocked), "suspect_golden_records": len(alerts),
                "dq_score_before": before, "dq_score_after": after}
