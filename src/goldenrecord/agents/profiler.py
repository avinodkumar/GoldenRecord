"""Profiler agent: profiles the data and authors rules and mappings once per pattern.

The LLM never touches individual records. It sees each distinct unknown value once ("Bangalore",
"ENGG", "RS"), proposes a mapping to a known canonical value, and the answer is cached. Validated,
confident mappings go into the versioned rule library automatically; the rest become steward patterns.
From then on standardization is a deterministic lookup: rerunning costs zero LLM calls.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import pandas as pd

from ..library import RuleLibrary, mapping_item
from ..mappings import DROP, canonical_cities, name_tokens, token_vocabulary, unmapped_cities, validate
from ..reference import LEGAL_TOKENS
from ..matching import name_similarity
from ..reference import VALID_CURRENCIES
from ..rules import run_rules
from .base import Agent, AgentContext

SUPPORTED_TYPES = ["not_null", "regex", "positive", "range", "allowed_values", "unique", "date_not_future"]
ENTITY_TABLES = {"vendor": "silver_vendor", "invoice": "silver_invoice"}
AUTO_APPROVE_AT = 0.90
RULE_FUZZY_MIN = 0.85
MAX_BLAST_RADIUS = 0.05   # a new rule that fails more than 5% of its table is blocked unless overridden
LLM_VALUES_PER_CALL = 40

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

MAPPING_SCHEMA = {
    "type": "object",
    "properties": {"mappings": {"type": "array", "items": {
        "type": "object",
        "properties": {"raw": {"type": "string"}, "canonical": {"type": ["string", "null"]},
                       "confidence": {"type": "number"}},
        "required": ["raw", "canonical", "confidence"], "additionalProperties": False}}},
    "required": ["mappings"], "additionalProperties": False,
}

FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {"findings": {"type": "array", "items": {"type": "string"}}},
    "required": ["findings"],
    "additionalProperties": False,
}

DOMAIN_PROMPTS = {
    "city": "Map each raw city name to the canonical city it refers to (aliases, old names, abbreviations).",
    "name_token": "Each raw token comes from a company name. Map it to the canonical word it abbreviates or "
                  "misspells (e.g. ENGG -> ENGINEERING).",
    "currency": "Map each raw currency code or symbol to the ISO currency it denotes.",
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
    role = "Profiles the data and authors mappings and rules once per pattern"

    # --- learning mappings (runs before Silver is built) -----------------------------------------
    def _ask_llm(self, ctx: AgentContext, domain: str, values: list[str], options: list[str]) -> dict:
        answers = {}
        for start in range(0, len(values), LLM_VALUES_PER_CALL):
            if ctx.llm is None or ctx.llm.stats.exhausted:
                break
            batch = values[start:start + LLM_VALUES_PER_CALL]
            result = ctx.llm.complete_json(
                "You curate reference data for a data-quality platform. " + DOMAIN_PROMPTS[domain]
                + " Choose canonical values only from the allowed list; return null when unsure. "
                  "Confidence is between 0 and 1.",
                f"Allowed canonical values: {options}\nRaw values: {batch}",
                MAPPING_SCHEMA,
            )
            for m in (result or {}).get("mappings", []):
                if m["raw"] in batch:
                    answers[m["raw"]] = (m["canonical"], max(0.0, min(1.0, float(m["confidence"]))))
        return answers

    def learn_mappings(self, ctx: AgentContext, names: pd.Series, cities: pd.Series, currencies: pd.Series) -> dict:
        lib = RuleLibrary(ctx.lake)
        mappings = lib.mappings()
        cache = ctx.lake.read("llm_mapping_cache")
        cached = {} if cache.empty else {(r.domain, r.raw_value): (r.canonical, float(r.confidence))
                                         for r in cache.itertuples()}
        core, rare_tokens = token_vocabulary(names, mappings)
        token_counts = pd.Series([t for n in names for t in set(name_tokens(n))]).value_counts()
        city_counts = cities.dropna().map(lambda v: v.strip().upper()).value_counts()
        cur_counts = currencies.dropna().map(lambda v: v.strip().upper()).value_counts()

        work = {
            "city": (unmapped_cities(cities, mappings, set()), canonical_cities(), city_counts),
            "name_token": (rare_tokens, sorted(core), token_counts),
            "currency": (sorted(v for v in cur_counts.index if v and v not in mappings.currency),
                         list(VALID_CURRENCIES), cur_counts),
        }
        approved, proposals, new_cache, llm_asked = [], [], [], 0
        for domain, (unknown, options, counts) in work.items():
            resolved: dict[str, tuple[str | None, float, str]] = {}
            to_ask = []
            for raw in unknown:
                if (domain, raw) in cached:
                    canonical, conf = cached[(domain, raw)]
                    resolved[raw] = (canonical, conf, "llm")
                    continue
                if domain in ("name_token", "city"):
                    pool = options if domain == "name_token" else [c.upper() for c in options]
                    best = max(pool, key=lambda o: name_similarity(raw, o), default=None)
                    score = name_similarity(raw, best) if best else 0.0
                    if best and score >= RULE_FUZZY_MIN and best[0] == raw[0] and abs(len(best) - len(raw)) <= 2:
                        canonical = best if domain == "name_token" else options[pool.index(best)]
                        resolved[raw] = (canonical, round(score, 3), "rule")
                        continue
                to_ask.append(raw)
            answers = self._ask_llm(ctx, domain, to_ask, options) if to_ask else {}
            llm_asked += len(answers)
            for raw, (canonical, conf) in answers.items():
                resolved[raw] = (canonical, conf, "llm")
                new_cache.append({"domain": domain, "raw_value": raw, "canonical": canonical, "confidence": conf,
                                  "model": ctx.llm.model if ctx.llm else "", "created_at": datetime.now(timezone.utc)})

            for raw in unknown:
                affected = int(counts.get(raw, 0))
                canonical, conf, source = resolved.get(raw, (None, 0.0, "none"))
                if canonical is None and domain == "name_token":  # best deterministic guess for a steward
                    legal = max(LEGAL_TOKENS, key=lambda o: name_similarity(raw, o))
                    best = max(options, key=lambda o: name_similarity(raw, o), default=None)
                    if legal[0] == raw[0] and name_similarity(raw, legal) >= 0.75 and len(raw) > 2:
                        canonical, conf, source = DROP, round(name_similarity(raw, legal), 3), "rule"
                    elif best and not validate(domain, raw, best, core):
                        canonical, conf, source = best, round(name_similarity(raw, best), 3), "rule"
                problem = validate(domain, raw, canonical, core)
                if canonical and not problem and conf >= AUTO_APPROVE_AT:
                    approved.append(mapping_item(domain, raw, canonical, conf, affected, source))
                elif affected:
                    similar = sorted(options, key=lambda o: -name_similarity(raw, str(o).upper()))[:5]
                    proposals.append({"domain": domain, "raw": raw, "canonical": None if problem else canonical,
                                      "confidence": conf, "affected": affected, "source": source,
                                      "options": similar, "reason": problem or f"confidence {conf:.2f}"})

        if new_cache:
            ctx.lake.append("llm_mapping_cache", pd.DataFrame(new_cache))
        version = lib.approve(approved, approved_by="auto-policy", source="policy", run_id=ctx.run_id,
                              note=f"validated, confidence >= {AUTO_APPROVE_AT}")
        ctx.state["mapping_proposals"] = proposals
        self.log(ctx, "mappings_learned",
                 f"{len(approved)} mappings added to the library (v{version or lib.version()}); "
                 f"{len(proposals)} sent to stewards; {llm_asked} values asked of the LLM, "
                 f"{sum(1 for d, *_ in work.items())} domains checked", used_llm=llm_asked > 0, records=len(approved))
        return {"auto_approved": len(approved), "proposals": len(proposals), "values_sent_to_llm": llm_asked}

    # --- profiling (runs after Silver is built) --------------------------------------------------
    def run(self, ctx: AgentContext) -> dict:
        frames = [profile_frame(ctx.state[key], table) for key, table in
                  (("vendors", "silver_vendor"), ("invoices", "silver_invoice"))]
        profile = pd.concat(frames, ignore_index=True).assign(run_id=ctx.run_id)
        ctx.lake.write("dq_profile", profile)
        worst = profile.sort_values("null_rate", ascending=False).head(5)
        findings = [f"{r.table}.{r.column}: {r.null_rate:.0%} empty" for r in worst.itertuples() if r.null_rate > 0]
        self.log(ctx, "profiled", " | ".join(findings) or "no notable gaps", records=len(profile))
        return {"columns_profiled": len(profile), "findings": findings}

    # --- authoring a rule from plain English -----------------------------------------------------
    def draft_rule(self, ctx: AgentContext, text: str, accept: bool = False, override: bool = False,
                   reviewer: str = "steward") -> dict:
        """Draft a rule, validate it, preview its blast radius on Silver, and (if accepted) add it to the
        library in shadow mode: it flags records but quarantines nothing until it is promoted."""
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

        lib = RuleLibrary(ctx.lake)
        rule = {**{k: v for k, v in rule.items() if v is not None},
                "id": f"C{len(lib.active('dq_rule')) + 1:02d}", "mode": "shadow"}
        empty = {e: df.iloc[0:0] for e, df in tables.items()}
        frames = {**empty, rule["entity"]: tables[rule["entity"]]}
        failures, summary = run_rules(frames["vendor"], frames["invoice"], [rule], ctx.as_of)
        preview = summary.iloc[0].to_dict()
        fail_rate = preview["failed"] / max(preview["evaluated"], 1)
        failing = failures.assign(source=failures["record_key"].str.split(":").str[0])
        by_source = failing.groupby("source").size().to_dict()
        blocked = fail_rate > MAX_BLAST_RADIUS
        result = {"ok": True, "rule": rule, "preview": {**preview, "fail_rate": round(fail_rate, 4),
                                                        "by_source": by_source},
                  "sample_failures": failures["record_key"].head(5).tolist(), "used_llm": used_llm,
                  "blocked": blocked, "saved": False,
                  "message": (f"Blocked: this rule would fail {fail_rate:.1%} of {rule['entity']} records "
                              f"(limit {MAX_BLAST_RADIUS:.0%}). Check the rule, or accept with override."
                              if blocked else "Within the blast-radius limit. Accepting adds it in shadow mode.")}
        if accept and (not blocked or override):
            version = lib.approve([{"item_id": f"DQ:{rule['id']}", "kind": "dq_rule", "definition": rule,
                                    "affected_records": int(preview["failed"]), "source": "llm" if used_llm else "rule"}],
                                  approved_by=reviewer, note=f"shadow; from: {text}" + (" (override)" if blocked else ""))
            result.update(saved=True, library_version=version)
        self.log(ctx, "rule_accepted" if result["saved"] else "rule_previewed",
                 f"{rule['id']} {rule['entity']}.{rule['column']} {rule['type']}: fails {preview['failed']} "
                 f"({fail_rate:.1%}){' BLOCKED' if blocked else ''}", used_llm, int(preview["failed"]))
        ctx.flush_events()
        return result

    def promote_rule(self, ctx: AgentContext, rule_id: str, reviewer: str) -> dict:
        """Move a shadow rule to enforce mode (new library version): from now on it quarantines."""
        lib = RuleLibrary(ctx.lake)
        item = next((i for i in lib.active("dq_rule") if i["definition"]["id"] == rule_id), None)
        if item is None:
            return {"ok": False, "error": f"{rule_id} is not an active rule"}
        definition = {**item["definition"], "mode": "enforce"}
        version = lib.approve([{"item_id": item["item_id"], "kind": "dq_rule", "definition": definition,
                                "affected_records": item["affected_records"], "source": item["source"]}],
                              approved_by=reviewer, note="promoted from shadow to enforce")
        self.log(ctx, "rule_promoted", f"{rule_id} now enforced (library v{version})")
        ctx.flush_events()
        return {"ok": True, "library_version": version, "rule": definition}
