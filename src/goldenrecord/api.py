"""GoldenRecord agent service (FastAPI). The single writer for pipeline runs; the UI calls it for actions.

Run: uvicorn goldenrecord.api:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date

import math
from datetime import datetime

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import synth
from .agents import ProfilerAgent, StewardAssistant
from .agents.base import AgentContext
from .agents.orchestrator import run_pipeline
from .llm import get_llm
from .store import Lakehouse

log = logging.getLogger("goldenrecord.api")
lake = Lakehouse()


def clean(obj):
    """Make agent output JSON-safe: numpy scalars to Python, NaN to null, dates to ISO strings."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if hasattr(obj, "isoformat"):  # pandas Timestamp
        return obj.isoformat()
    return obj


def _ctx() -> AgentContext:
    return AgentContext(lake=lake, llm=get_llm(), run_id=f"adhoc-{uuid.uuid4().hex[:8]}", as_of=date.today())


def _scheduler(minutes: float) -> None:
    while True:
        time.sleep(minutes * 60)
        try:
            run_pipeline(lake)
        except Exception:
            log.exception("scheduled run failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if os.environ.get("BOOTSTRAP", "true").lower() == "true":
        if not (lake.landing_dir / "ERP_A" / "vendors.csv").exists():
            log.info("no extracts in landing; generating synthetic multi-ERP data")
            synth.generate(raw_dir=lake.landing_dir, truth_dir=lake.truth_dir)
        if not lake.exists("gold_vendor"):
            threading.Thread(target=run_pipeline, args=(lake,), daemon=True).start()
    minutes = float(os.environ.get("SCHEDULE_MINUTES", "0"))
    if minutes > 0:
        threading.Thread(target=_scheduler, args=(minutes,), daemon=True).start()
    yield


app = FastAPI(title="GoldenRecord agents", version="0.2.0", lifespan=lifespan)


class GenerateRequest(BaseModel):
    vendors: int = 3000
    invoices: int = 45000
    seed: int = 42


class RuleRequest(BaseModel):
    text: str
    accept: bool = False


class PairRequest(BaseModel):
    left_key: str
    right_key: str


class DecisionRequest(PairRequest):
    decision: str
    reviewer: str
    note: str = ""


@app.get("/health")
def health():
    llm = get_llm()
    return {"status": "ok", "llm": f"{llm.provider}:{llm.model}" if llm else "none (rules only)",
            "tables": lake.tables()}


@app.post("/runs")
def trigger_run():
    return clean(run_pipeline(lake))


@app.get("/runs")
def runs(limit: int = 20):
    df = lake.read("run_history")
    if df.empty:
        return []
    return clean(df.sort_values("run_at", ascending=False).head(limit).to_dict("records"))


@app.post("/data/generate")
def generate(req: GenerateRequest):
    """Replace the landing extracts with fresh synthetic data and reset the lakehouse tables."""
    shutil.rmtree(lake.landing_dir, ignore_errors=True)
    shutil.rmtree(lake.tables_dir, ignore_errors=True)
    lake.tables_dir.mkdir(parents=True, exist_ok=True)
    return synth.generate(req.vendors, req.invoices, req.seed, raw_dir=lake.landing_dir, truth_dir=lake.truth_dir)


@app.post("/demo/bad-batch")
def bad_batch(rows: int = 3000):
    return synth.inject_bad_batch(lake.landing_dir, rows, truth_dir=lake.truth_dir)


@app.delete("/demo/bad-batch")
def clear_bad_batch():
    return {"removed": synth.remove_bad_batch(lake.landing_dir)}


@app.post("/rules/draft")
def draft_rule(req: RuleRequest):
    if not lake.exists("silver_vendor"):
        raise HTTPException(409, "run the pipeline first so the Profiler has Silver data to check against")
    return clean(ProfilerAgent().draft_rule(_ctx(), req.text, req.accept))


@app.get("/review/queue")
def review_queue(limit: int = 50):
    df = lake.read("review_queue")
    return [] if df.empty else clean(df.sort_values("score", ascending=False).head(limit).to_dict("records"))


@app.post("/review/recommend")
def recommend(req: PairRequest):
    result = StewardAssistant().recommend(_ctx(), req.left_key, req.right_key)
    if not result["ok"]:
        raise HTTPException(404, result["error"])
    return clean(result)


@app.post("/review/decisions")
def decide(req: DecisionRequest):
    result = StewardAssistant().record_decision(_ctx(), req.left_key, req.right_key, req.decision,
                                                req.reviewer, req.note)
    if not result["ok"]:
        raise HTTPException(400, result["error"])
    return clean(result)


@app.post("/learning/train")
def train():
    return clean(StewardAssistant().train(_ctx()))


@app.get("/alerts")
def alerts(limit: int = 20):
    df = lake.read("alerts")
    return [] if df.empty else clean(df.sort_values("raised_at", ascending=False).head(limit).to_dict("records"))
