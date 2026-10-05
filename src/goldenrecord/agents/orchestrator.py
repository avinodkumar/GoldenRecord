"""Orchestrator: the Data Factory pipeline stand-in. Lands extracts in Bronze, builds Silver, then runs
the agents in order: Profiler -> Quality -> Matcher -> Gatekeeper -> Sentinel."""
from __future__ import annotations

import threading
import time
import uuid
from datetime import date, datetime, timezone

import pandas as pd

from .. import config
from ..evaluate import pairwise_match_metrics, rule_catch_metrics
from ..llm import LLMClient, get_llm
from ..standardize import standardize_invoices, standardize_vendors
from ..store import Lakehouse
from .base import AgentContext
from .gatekeeper import GatekeeperAgent
from .matcher import MatcherAgent
from .profiler import ProfilerAgent
from .quality import QualityAgent
from .sentinel import SentinelAgent

PIPELINE = [ProfilerAgent(), QualityAgent(), MatcherAgent(), GatekeeperAgent(), SentinelAgent()]
_run_lock = threading.Lock()


def _read_landing(lake: Lakehouse, source: str, entity: str) -> pd.DataFrame:
    files = sorted((lake.landing_dir / source).glob(f"{entity}*.csv"))
    if not files:
        raise FileNotFoundError(f"no {entity} extract in {lake.landing_dir / source}")
    frames = []
    for f in files:
        df = pd.read_csv(f, dtype=str, keep_default_na=False)
        frames.append(df.assign(_source_file=f.name))
    return pd.concat(frames, ignore_index=True)


def ingest_and_standardize(lake: Lakehouse, ingested_at: datetime) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Bronze: each extract as-is with lineage columns. Silver: one canonical schema."""
    vendors, invoices = [], []
    for source in config.SOURCES:
        for entity, target in (("vendors", vendors), ("invoices", invoices)):
            raw = _read_landing(lake, source, entity)
            lake.write(f"bronze_{source.lower()}_{entity}",
                       raw.assign(_source_system=source, _ingested_at=ingested_at))
            body = raw.drop(columns=["_source_file"])
            target.append(standardize_vendors(body, source) if entity == "vendors"
                          else standardize_invoices(body, source))
    silver_vendor = pd.concat(vendors, ignore_index=True)
    silver_invoice = pd.concat(invoices, ignore_index=True)
    lake.write("silver_vendor", silver_vendor)
    lake.write("silver_invoice", silver_invoice)
    return silver_vendor, silver_invoice


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
        vendors, invoices = ingest_and_standardize(lake, started)
        ctx.state.update(vendors=vendors, invoices=invoices)

        results = {}
        for agent in PIPELINE:
            results[agent.name] = agent.run(ctx)
            ctx.flush_events()

        summary = {
            "run_id": run_id,
            "run_at": started.isoformat(timespec="seconds"),
            "seconds": round(time.perf_counter() - t0, 1),
            "llm": f"{llm.provider}:{llm.model}" if llm else "none (rules only)",
            "llm_calls": llm.stats.calls if llm else 0,
            "llm_failures": llm.stats.failures if llm else 0,
            "silver_vendor_records": len(vendors),
            "silver_invoice_records": len(invoices),
            "golden_vendors": results["gatekeeper"]["golden_vendors"],
            "review_queue": results["gatekeeper"]["review_queue"],
            "quarantined_invoices": results["gatekeeper"]["quarantined_invoices"],
            "gold_spend_usd": round(float(ctx.state["spend"]["amount_usd"].sum()), 2),
            "dq_score_before": results["gatekeeper"]["dq_score_before"],
            "dq_score_after": results["gatekeeper"]["dq_score_after"],
            "active_rules": results["quality"]["active_rules"],
            "alerts": ",".join(results["sentinel"]["alerts"]),
        }
        truth = lake.truth_dir / "vendor_truth.csv"
        if truth.exists():
            t = pd.read_csv(truth, dtype=str)
            defects = pd.read_csv(lake.truth_dir / "seeded_defects.csv", dtype=str, keep_default_na=False)
            defects = defects.replace("", None)
            summary.update(pairwise_match_metrics(ctx.state["xref"], t))
            catch = rule_catch_metrics(ctx.state["flags"], defects, invoices)
            summary.update(catch_rate=catch["catch_rate"], false_quarantine_rate=catch["false_quarantine_rate"])
        lake.append("run_history", pd.DataFrame([summary]))
        return {"summary": summary, "agents": results}
