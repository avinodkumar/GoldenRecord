"""Quality agent: runs the rule catalog (base + steward-approved) and the anomaly check."""
from __future__ import annotations

import pandas as pd

from ..rules import detect_amount_anomalies, load_rules, run_rules
from .base import Agent, AgentContext

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": False,
}


def custom_rules(ctx: AgentContext) -> list[dict]:
    df = ctx.lake.read("dq_rules_custom")
    rules = []
    for row in df.to_dict("records"):
        rule = {k: v for k, v in row.items() if v is not None and not (isinstance(v, float) and pd.isna(v))
                and k not in ("created_at", "source_text")}
        if isinstance(rule.get("values"), str):
            rule["values"] = rule["values"].split(",")
        rules.append(rule)
    return rules


class QualityAgent(Agent):
    name = "quality"
    role = "Runs the data-quality rules and anomaly check, and explains the results"

    def run(self, ctx: AgentContext) -> dict:
        vendors, invoices = ctx.state["vendors"], ctx.state["invoices"]
        rules = load_rules() + custom_rules(ctx)
        failures, scorecard = run_rules(vendors, invoices, rules, ctx.as_of)
        anomalies = detect_amount_anomalies(invoices)
        flags = pd.concat([failures, anomalies], ignore_index=True)
        scorecard = pd.concat([scorecard, pd.DataFrame([{
            "rule_id": "A01", "name": "Invoice amount is not an outlier for its vendor", "entity": "invoice",
            "dimension": "accuracy", "severity": "medium", "evaluated": len(invoices), "failed": len(anomalies),
            "pass_rate": round(1 - len(anomalies) / max(len(invoices), 1), 4)}])], ignore_index=True)

        ctx.lake.write("silver_dq_failures", flags)
        ctx.lake.write("dq_scorecard", scorecard)
        ctx.lake.append("dq_scorecard_history", scorecard.assign(run_id=ctx.run_id))
        ctx.state.update(rules=rules, flags=flags, scorecard=scorecard)

        worst = scorecard.sort_values("pass_rate").head(3)
        summary = "Weakest rules: " + "; ".join(
            f"{r.rule_id} {r.name} ({r.failed} failures, {r.pass_rate:.1%} pass)" for r in worst.itertuples())
        used_llm = False
        if ctx.llm:
            result = ctx.llm.complete_json(
                "You are a data-quality lead writing a two-sentence run summary for executives. "
                "Use only the numbers given.",
                "Scorecard:\n" + scorecard[["rule_id", "name", "failed", "pass_rate"]].to_csv(index=False),
                SUMMARY_SCHEMA,
            )
            if result:
                summary, used_llm = result["summary"], True
        self.log(ctx, "rules_evaluated", summary, used_llm, len(flags))
        return {"active_rules": len(rules), "failures": len(flags), "anomalies": len(anomalies), "summary": summary}
