"""Orchestrator (the Data Factory pipeline in Fabric; local stand-in for development).

Order of a run:
  1. Ingest      landing extracts -> PII tokenized and masked -> Bronze; raw PII -> restricted pii_vault
  2. Learn       Profiler authors mappings for values never seen before (once per pattern, cached)
  3. Silver      deterministic standardization using the versioned rule library; approved record fixes applied
  4. Agents      Profiler (profile) -> Quality -> Matcher -> Gatekeeper -> Steward (patterns) -> Sentinel
"""
from __future__ import annotations

import threading
import time
import uuid
from datetime import date, datetime, timezone

import pandas as pd

from .. import config
from ..evaluate import pairwise_match_metrics, rule_catch_metrics
from ..fixes import apply_record_fixes
from ..library import RuleLibrary
from ..llm import LLMClient, get_llm
from ..privacy import protect_vendor_pii
from ..standardize import SOURCE_SCHEMAS, standardize_invoices, standardize_vendors
from ..store import Lakehouse
from .base import AgentContext
from .gatekeeper import GatekeeperAgent
from .matcher import MatcherAgent
from .profiler import ProfilerAgent
from .quality import QualityAgent
from .sentinel import SentinelAgent
from .steward import StewardAssistant

PIPELINE = [ProfilerAgent(), QualityAgent(), MatcherAgent(), GatekeeperAgent(), StewardAssistant(), SentinelAgent()]
_run_lock = threading.Lock()


def _read_landing(lake: Lakehouse, source: str, entity: str) -> pd.DataFrame:
    files = sorted((lake.landing_dir / source).glob(f"{entity}*.csv"))
    if not files:
        raise FileNotFoundError(f"no {entity} extract in {lake.landing_dir / source}")
    return pd.concat([pd.read_csv(f, dtype=str, keep_default_na=False).assign(_source_file=f.name) for f in files],
                     ignore_index=True)


def ingest_bronze(lake: Lakehouse, ingested_at: datetime) -> dict[str, pd.DataFrame]:
    """Bronze holds every source column, but personal data only as masked values and tokens."""
    bronze, vault = {}, []
    for source in config.SOURCES:
        vendors, pii = protect_vendor_pii(_read_landing(lake, source, "vendors"), source)
        vault.append(pii)
        for entity, df in (("vendors", vendors), ("invoices", _read_landing(lake, source, "invoices"))):
            df = df.assign(_source_system=source, _ingested_at=ingested_at)
            lake.write(f"bronze_{source.lower()}_{entity}", df)
            bronze[f"{source}_{entity}"] = df
    lake.write("pii_vault", pd.concat(vault, ignore_index=True))  # restricted: pii-custodian role only
    return bronze


def build_silver(lake: Lakehouse, bronze: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    lib = RuleLibrary(lake)
    mappings = lib.mappings()
    drop = ["_source_system", "_ingested_at", "_source_file"]
    vendors = pd.concat([standardize_vendors(bronze[f"{s}_vendors"].drop(columns=drop), s, mappings)
                         for s in config.SOURCES], ignore_index=True)
    invoices = pd.concat([standardize_invoices(bronze[f"{s}_invoices"].drop(columns=drop), s, mappings)
                          for s in config.SOURCES], ignore_index=True)
    invoices = apply_record_fixes(invoices, vendors, lib.record_fixes())
    lake.write("silver_vendor", vendors)
    lake.write("silver_invoice", invoices)
    return vendors, invoices


def _raw_column(bronze, entity: str, field: str) -> pd.Series:
    return pd.concat([bronze[f"{s}_{entity}"][{v: k for k, v in SOURCE_SCHEMAS[s][entity].items()}[field]]
                      for s in config.SOURCES], ignore_index=True)


def run_pipeline(lake: Lakehouse | None = None, llm: LLMClient | None = None, as_of: date | None = None,
                 use_env_llm: bool = True) -> dict:
    lake = lake or Lakehouse()
    if llm is None and use_env_llm:
        llm = get_llm()
    with _run_lock:
        started = datetime.now(timezone.utc)
        run_id = started.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
        ctx = AgentContext(lake=lake, llm=llm, run_id=run_id, as_of=as_of or date.today())
        t0 = time.perf_counter()

        bronze = ingest_bronze(lake, started)
        learned = PIPELINE[0].learn_mappings(ctx, _raw_column(bronze, "vendors", "vendor_name"),
                                             _raw_column(bronze, "vendors", "city_raw"),
                                             _raw_column(bronze, "invoices", "currency_raw"))
        ctx.flush_events()
        vendors, invoices = build_silver(lake, bronze)
        ctx.state.update(vendors=vendors, invoices=invoices)

        results = {"learning": learned}
        for agent in PIPELINE:
            results[agent.name] = agent.run(ctx)
            ctx.flush_events()

        gk, st = results["gatekeeper"], results["steward"]
        summary = {
            "run_id": run_id,
            "run_at": started.isoformat(timespec="seconds"),
            "seconds": round(time.perf_counter() - t0, 1),
            "library_version": RuleLibrary(lake).version(),
            "llm": f"{llm.provider}:{llm.model}" if llm else "none (rules only)",
            "llm_calls": llm.stats.calls if llm else 0,
            "llm_failures": llm.stats.failures if llm else 0,
            "values_sent_to_llm": learned["values_sent_to_llm"],
            "pairs_sent_to_llm": results["matcher"]["llm_reviewed"],
            "pairs_from_cache": results["matcher"]["from_cache"],
            "silver_vendor_records": len(vendors),
            "silver_invoice_records": len(invoices),
            "records_fixed": int(invoices["fixed_by"].notna().sum()),
            "golden_vendors": gk["golden_vendors"],
            "review_queue": gk["review_queue"],
            "suspect_golden_records": gk["suspect_golden_records"],
            "quarantined_invoices": gk["quarantined_invoices"],
            "issue_records": st["issue_records"],
            "open_patterns": st["open_patterns"],
            "top10_coverage": st["top10_coverage"],
            "gold_spend_usd": round(float(ctx.state["spend"]["amount_usd"].sum()), 2),
            "dq_score_before": gk["dq_score_before"],
            "dq_score_after": gk["dq_score_after"],
            "active_rules": results["quality"]["active_rules"],
            "shadow_rules": results["quality"]["shadow_rules"],
            "alerts": ",".join(results["sentinel"]["alerts"]),
        }
        truth = lake.truth_dir / "vendor_truth.csv"
        if truth.exists():
            t = pd.read_csv(truth, dtype=str)
            defects = pd.read_csv(lake.truth_dir / "seeded_defects.csv", dtype=str, keep_default_na=False)
            defects = defects.replace("", None)
            summary.update(pairwise_match_metrics(ctx.state["xref"], t))
            fixed = set(invoices.loc[invoices["fixed_by"].notna(), "record_key"])
            catch = rule_catch_metrics(ctx.state["flags"], defects, invoices, fixed)
            summary.update(catch_rate=catch["catch_rate"], false_quarantine_rate=catch["false_quarantine_rate"])
        lake.append("run_history", pd.DataFrame([summary]))
        return {"summary": summary, "agents": results}
