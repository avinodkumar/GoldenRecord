"""Quality agent: runs the rule catalog (base + library rules) and the anomaly check.

Library rules in shadow mode are evaluated and reported but never quarantine anything; only
enforced rules gate records into Gold. That is the safety net for a badly authored rule.
"""
from __future__ import annotations

import pandas as pd

from ..library import RuleLibrary
from ..rules import detect_amount_anomalies, load_rules, run_rules
from .base import Agent, AgentContext


class QualityAgent(Agent):
    name = "quality"
    role = "Runs the data-quality rules and anomaly check, enforcing only approved rules"

    def run(self, ctx: AgentContext) -> dict:
        vendors, invoices = ctx.state["vendors"], ctx.state["invoices"]
        base = [{**r, "mode": "enforce"} for r in load_rules()]
        custom = RuleLibrary(ctx.lake).dq_rules()
        rules = base + custom
        failures, scorecard = run_rules(vendors, invoices, rules, ctx.as_of)
        anomalies = detect_amount_anomalies(invoices)
        mode = {r["id"]: r.get("mode", "enforce") for r in rules} | {"A01": "enforce"}
        flags = pd.concat([failures, anomalies], ignore_index=True)
        flags["mode"] = flags["rule_id"].map(mode)
        scorecard = pd.concat([scorecard, pd.DataFrame([{
            "rule_id": "A01", "name": "Invoice amount is not an outlier for its vendor", "entity": "invoice",
            "dimension": "accuracy", "severity": "medium", "evaluated": len(invoices), "failed": len(anomalies),
            "pass_rate": round(1 - len(anomalies) / max(len(invoices), 1), 4)}])], ignore_index=True)
        scorecard["mode"] = scorecard["rule_id"].map(mode)

        enforced_flags = flags[flags["mode"] == "enforce"]
        ctx.lake.write("silver_dq_failures", flags)
        ctx.lake.write("dq_scorecard", scorecard)
        ctx.lake.append("dq_scorecard_history", scorecard.assign(run_id=ctx.run_id))
        ctx.state.update(rules=rules, flags=enforced_flags, all_flags=flags, scorecard=scorecard,
                         enforced_rules={rid for rid, m in mode.items() if m == "enforce"})

        worst = scorecard[scorecard["mode"] == "enforce"].sort_values("pass_rate").head(3)
        shadow = scorecard[scorecard["mode"] == "shadow"]
        summary = "Weakest rules: " + "; ".join(
            f"{r.rule_id} {r.name} ({r.failed} failures, {r.pass_rate:.1%} pass)" for r in worst.itertuples())
        if len(shadow):
            summary += " | Shadow rules (not enforced): " + "; ".join(
                f"{r.rule_id} would fail {r.failed}" for r in shadow.itertuples())
        self.log(ctx, "rules_evaluated", summary, records=len(enforced_flags))
        return {"active_rules": len(rules), "shadow_rules": len(shadow), "failures": len(enforced_flags),
                "anomalies": len(anomalies), "summary": summary}
