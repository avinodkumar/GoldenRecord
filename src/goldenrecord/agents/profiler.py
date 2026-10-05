"""Profiler agent: profiles Silver data and turns plain-English requests into validated DQ rules."""
from __future__ import annotations

import re
from datetime import datetime, timezone

import pandas as pd

from ..rules import run_rules
from .base import Agent, AgentContext

SUPPORTED_TYPES = ["not_null", "regex", "positive", "range", "allowed_values", "unique", "date_not_future"]
ENTITY_TABLES = {"vendor": "silver_vendor", "invoice": "silver_invoice"}

RULE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "entity": {"type": "string", "enum": list(ENTITY_TABLES)},
        "column": {"type": "string"},
        "type": {"type": "string", "enum": SUPPORTED_TYPES},
        "pattern": {"type": ["string", "null"]},
        "values": {"type": ["array", "null"], "items": {"type": "string"}},
        "min": {"type": ["number", "null"]},
        "max": {"type": ["number", "null"]},
        "dimension": {"type": "string", "enum": ["completeness", "validity", "uniqueness", "timeliness",
                                                 "consistency"]},
        "severity": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["name", "entity", "column", "type", "pattern", "values", "min", "max", "dimension", "severity"],
    "additionalProperties": False,
}

FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {"findings": {"type": "array", "items": {"type": "string"}}},
    "required": ["findings"],
    "additionalProperties": False,
}


def shape(value) -> str | None:
    """Pattern mask: letters -> A, digits -> 9, everything else kept. 'IN4F7K' -> 'AA9A9A'."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return re.sub(r"[0-9]", "9", re.sub(r"[A-Za-z]", "A", str(value)))[:24]


def profile_frame(df: pd.DataFrame, table: str) -> pd.DataFrame:
    rows = []
    n = len(df)
    for col in df.columns:
        s = df[col]
        shapes = s.map(shape).dropna()
        top = shapes.value_counts().head(3)
        rows.append({
            "table": table, "column": col, "rows": n,
            "null_rate": round(float(s.isna().mean()), 4) if n else 0.0,
            "distinct": int(s.astype(str).nunique()),
            "top_patterns": "; ".join(f"{p} ({c / max(len(shapes), 1):.0%})" for p, c in top.items()),
        })
    return pd.DataFrame(rows)


def _heuristic_rule(text: str, columns: dict[str, list[str]]) -> dict | None:
    """Rules-only fallback for common phrasings, e.g. 'vendor email must not be empty'."""
    t = text.lower()
    entity = "invoice" if "invoice" in t else "vendor"
    column = next((c for c in sorted(columns[entity], key=len, reverse=True)
                   if c.replace("_", " ") in t or c in t), None)
    if column is None:
        return None
    rule = {"name": text.strip().rstrip(".").capitalize(), "entity": entity, "column": column,
            "pattern": None, "values": None, "min": None, "max": None, "severity": "medium"}
    if re.search(r"unique|duplicate", t):
        return {**rule, "type": "unique", "dimension": "uniqueness"}
    if re.search(r"not be (empty|blank|null|missing)|is required|must be present|mandatory", t):
        return {**rule, "type": "not_null", "dimension": "completeness"}
    if re.search(r"positive|greater than (0|zero)", t):
        return {**rule, "type": "positive", "dimension": "validity"}
    m = re.search(r"(?:at most|not exceed|no more than|below|under)\s+([\d,\.]+)", t)
    if m:
        return {**rule, "type": "range", "max": float(m.group(1).replace(",", "")), "dimension": "validity"}
    m = re.search(r"(?:at least|no less than|above|over)\s+([\d,\.]+)", t)
    if m:
        return {**rule, "type": "range", "min": float(m.group(1).replace(",", "")), "dimension": "validity"}
    if "future" in t:
        return {**rule, "type": "date_not_future", "dimension": "timeliness"}
    return None


class ProfilerAgent(Agent):
    name = "profiler"
    role = "Profiles Silver tables and drafts new data-quality rules from plain English"

    def run(self, ctx: AgentContext) -> dict:
        frames = [profile_frame(ctx.state[key], table) for key, table in
                  (("vendors", "silver_vendor"), ("invoices", "silver_invoice"))]
        profile = pd.concat(frames, ignore_index=True).assign(run_id=ctx.run_id)
        ctx.lake.write("dq_profile", profile)

        worst = profile.sort_values("null_rate", ascending=False).head(5)
        findings = [f"{r.table}.{r.column}: {r.null_rate:.0%} empty" for r in worst.itertuples() if r.null_rate > 0]
        used_llm = False
        if ctx.llm:
            result = ctx.llm.complete_json(
                "You are a data-quality analyst. Write short, factual findings for a data steward. "
                "Only state what the profile shows.",
                "Column profile (table, column, null_rate, distinct, top_patterns):\n"
                + profile[["table", "column", "null_rate", "distinct", "top_patterns"]].to_csv(index=False)
                + "\nGive at most 5 findings about likely data-quality problems.",
                FINDINGS_SCHEMA,
            )
            if result and result.get("findings"):
                findings, used_llm = result["findings"][:5], True
        self.log(ctx, "profiled", " | ".join(findings) or "no notable gaps", used_llm, len(profile))
        return {"columns_profiled": len(profile), "findings": findings}

    def draft_rule(self, ctx: AgentContext, text: str, accept: bool = False) -> dict:
        """Turn a sentence into a rule, validate it, dry-run it on Silver, and save it if accepted."""
        tables = {e: ctx.lake.read(t) for e, t in ENTITY_TABLES.items()}
        columns = {e: list(df.columns) for e, df in tables.items()}
        rule, used_llm = None, False
        if ctx.llm:
            rule = ctx.llm.complete_json(
                "You convert a data steward's sentence into one data-quality rule. Use only the listed "
                "columns and rule types. Set unused fields to null.",
                f"Columns: {columns}\nRule types: {SUPPORTED_TYPES}\nSentence: {text}",
                RULE_SCHEMA,
            )
            used_llm = rule is not None
        if rule is None:
            rule = _heuristic_rule(text, columns)
        if rule is None:
            return {"ok": False, "error": "Could not turn this sentence into a rule. Name a column and a condition."}

        # Guardrail: the LLM's draft must use a real column and a supported type before it can run.
        problems = []
        if rule["entity"] not in columns or rule["column"] not in columns[rule["entity"]]:
            problems.append(f"unknown column {rule['entity']}.{rule['column']}")
        if rule["type"] not in SUPPORTED_TYPES:
            problems.append(f"unsupported rule type {rule['type']}")
        if rule["type"] == "regex":
            try:
                re.compile(rule["pattern"] or "")
            except re.error as exc:
                problems.append(f"invalid regex: {exc}")
        if problems:
            return {"ok": False, "error": "; ".join(problems), "rule": rule}

        existing = ctx.lake.read("dq_rules_custom")
        rule = {**{k: v for k, v in rule.items() if v is not None}, "id": f"C{len(existing) + 1:02d}"}
        empty = {"vendor": tables["vendor"].iloc[0:0], "invoice": tables["invoice"].iloc[0:0]}
        frames = {**empty, rule["entity"]: tables[rule["entity"]]}
        failures, summary = run_rules(frames["vendor"], frames["invoice"], [rule], ctx.as_of)
        dry_run = summary.iloc[0].to_dict()
        sample = failures["record_key"].head(5).tolist()

        if accept:
            row = {**rule, "values": ",".join(rule.get("values", []) or []) or None,
                   "created_at": datetime.now(timezone.utc), "source_text": text}
            ctx.lake.append("dq_rules_custom", pd.DataFrame([row]))
        self.log(ctx, "rule_accepted" if accept else "rule_drafted",
                 f"{rule['id']} {rule['entity']}.{rule['column']} {rule['type']}: fails {dry_run['failed']} records",
                 used_llm, int(dry_run["failed"]))
        ctx.flush_events()
        return {"ok": True, "rule": rule, "dry_run": dry_run, "sample_failures": sample, "saved": accept,
                "used_llm": used_llm}
