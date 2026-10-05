"""Shared agent plumbing: run context and the audit trail every agent writes to."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import pandas as pd

from ..llm import LLMClient
from ..store import Lakehouse


@dataclass
class AgentContext:
    lake: Lakehouse
    llm: LLMClient | None
    run_id: str
    as_of: date
    events: list[dict] = field(default_factory=list)
    state: dict = field(default_factory=dict)  # in-memory hand-off between agents within a run

    def flush_events(self) -> None:
        if self.events:
            self.lake.append("agent_events", pd.DataFrame(self.events))
            self.events.clear()


class Agent:
    """An agent owns one step of the run, logs what it decided and why, and degrades to rules-only."""

    name = "agent"
    role = ""

    def log(self, ctx: AgentContext, action: str, detail: str, used_llm: bool = False, records: int = 0) -> None:
        ctx.events.append({
            "run_id": ctx.run_id,
            "logged_at": datetime.now(timezone.utc),
            "agent": self.name,
            "action": action,
            "detail": detail,
            "used_llm": used_llm,
            "records": records,
        })

    def run(self, ctx: AgentContext) -> dict:
        raise NotImplementedError
