"""Sentinel agent: watches run metrics like Fabric Activator and raises explained alerts."""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime, timezone

import pandas as pd
import yaml

from ..config import CONFIG_DIR
from .base import Agent, AgentContext

log = logging.getLogger(__name__)

CAUSE_SCHEMA = {
    "type": "object",
    "properties": {"cause": {"type": "string"}, "action": {"type": "string"}},
    "required": ["cause", "action"],
    "additionalProperties": False,
}


def load_alert_rules(path=CONFIG_DIR / "alert_rules.yaml") -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["rules"]


def evaluate(rule: dict, current: dict, previous: dict | None) -> tuple[bool, float | None]:
    value = current.get(rule["metric"])
    if value is None:
        return False, None
    cond, threshold = rule["condition"], rule["threshold"]
    if cond == "below":
        return value < threshold, value
    if cond == "above":
        return value > threshold, value
    if previous is None or previous.get(rule["metric"]) is None:
        return False, value
    delta = value - previous[rule["metric"]]
    if cond == "drop_vs_previous":
        return -delta > threshold, delta
    if cond == "rise_vs_previous":
        return delta > threshold, delta
    raise ValueError(f"unknown condition {cond!r}")


def _post_webhook(url: str, text: str) -> bool:
    try:
        req = urllib.request.Request(url, data=json.dumps({"text": text}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10).close()
        return True
    except Exception as exc:
        log.warning("alert webhook failed: %s", exc)
        return False


class SentinelAgent(Agent):
    name = "sentinel"
    role = "Watches each run's quality metrics and raises alerts with a likely cause"

    def run(self, ctx: AgentContext) -> dict:
        s = ctx.state
        scorecard = s["scorecard"]
        worst = scorecard.sort_values("pass_rate").iloc[0]
        all_keys = pd.concat([s["vendors"]["record_key"], s["invoices"]["record_key"]])
        metrics = {
            "run_id": ctx.run_id,
            "run_at": datetime.now(timezone.utc),
            "records": len(all_keys),
            "pass_rate": round(float((~all_keys.isin(set(s["flags"]["record_key"]))).mean()), 4),
            "anomalies": int((s["flags"]["rule_id"] == "A01").sum()),
            "worst_rule": worst["rule_id"],
            "worst_rule_pass_rate": float(worst["pass_rate"]),
            "quarantine_rate": round(len(s["quarantine"]) / max(len(s["invoices"]), 1), 4),
            "dq_score_after": s["dq_after"],
            "suspect_golden_records": len(s.get("cluster_alerts", [])),
        }
        failing = set(s["flags"]["record_key"])
        source_scores = (all_keys.to_frame("record_key")
                         .assign(source_system=lambda d: d["record_key"].str.split(":").str[0],
                                 passed=lambda d: ~d["record_key"].isin(failing))
                         .groupby("source_system")["passed"].mean().round(4))
        source_history = ctx.lake.read("dq_source_score_history")
        prev_source = ({} if source_history.empty else source_history.sort_values("scored_at")
                       .drop_duplicates("source_system", keep="last").set_index("source_system")["dq_score"].to_dict())
        ctx.lake.append("dq_source_score_history", pd.DataFrame({
            "source_system": source_scores.index, "dq_score": source_scores.values,
            "run_id": ctx.run_id, "scored_at": metrics["run_at"]}))
        history = ctx.lake.read("dq_run_metrics")
        previous = history.sort_values("run_at").iloc[-1].to_dict() if not history.empty else None
        ctx.lake.append("dq_run_metrics", pd.DataFrame([metrics]))

        rule_deltas = ""
        if previous is not None:
            prev_card = ctx.lake.read("dq_scorecard_history")
            before = prev_card[prev_card["run_id"] == previous["run_id"]].set_index("rule_id")["failed"]
            delta = (scorecard.set_index("rule_id")["failed"] - before.reindex(scorecard["rule_id"]).fillna(0))
            top = delta.sort_values(ascending=False).head(3)
            rule_deltas = ", ".join(f"{rid} +{int(d)}" for rid, d in top.items() if d > 0)

        checks = []
        for rule in load_alert_rules():
            if rule["metric"] == "source_dq_score":  # one check per ERP source (Activator object = source)
                for src, score in source_scores.items():
                    fired, value = evaluate({**rule, "metric": "score"}, {"score": score},
                                            {"score": prev_source.get(src)} if src in prev_source else None)
                    checks.append(({**rule, "name": f"{rule['name']}: {src}"}, fired, value))
            else:
                checks.append((rule, *evaluate(rule, metrics, previous)))
        alerts = []
        for rule, fired, value in checks:
            if not fired:
                continue
            cause = (f"Largest increases in failures: {rule_deltas}." if rule_deltas
                     else f"Weakest rule this run: {worst['rule_id']} ({worst['name']}).")
            action, used_llm = "Open the quarantine list for the named rules and check the latest extract.", False
            if ctx.llm:
                result = ctx.llm.complete_json(
                    "You write a short data-quality alert for a data-steward channel: the likely cause and the "
                    "first action. Use only the numbers given.",
                    f"Alert: {rule['name']} ({rule['metric']} {rule['condition']} {rule['threshold']}, value {value}).\n"
                    f"Current metrics: {metrics}\nPrevious run: {previous}\nRule failure changes: {rule_deltas}",
                    CAUSE_SCHEMA,
                )
                if result:
                    cause, action, used_llm = result["cause"], result["action"], True
            text = f"[{rule['severity'].upper()}] {rule['id']} {rule['name']}: {cause} Next step: {action}"
            sent = _post_webhook(os.environ["ALERT_WEBHOOK_URL"], text) if os.environ.get("ALERT_WEBHOOK_URL") else False
            alerts.append({"run_id": ctx.run_id, "raised_at": metrics["run_at"], "alert_id": rule["id"],
                           "name": rule["name"], "severity": rule["severity"], "metric": rule["metric"],
                           "value": None if value is None else float(value), "cause": cause, "action": action,
                           "webhook_sent": sent})
            self.log(ctx, "alert_raised", text, used_llm)

        if alerts:
            ctx.lake.append("alerts", pd.DataFrame(alerts))
        else:
            self.log(ctx, "all_clear", f"pass rate {metrics['pass_rate']:.1%}, {metrics['anomalies']} anomalies")
        return {"alerts": [a["alert_id"] for a in alerts], "pass_rate": metrics["pass_rate"]}
