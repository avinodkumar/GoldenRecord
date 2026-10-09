"""Learned value mappings: the LLM authors a mapping once per distinct pattern, then it is reused
deterministically ("Bangalore" -> "Bengaluru", "ENGG" -> "ENGINEERING", "LOGISTCS" -> "LOGISTICS").

The mapping table (ref_value_mapping) is the cache. Rows record who authored each mapping (seed, rule,
llm, steward), with what confidence, and whether it is approved. Only approved rows are applied.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

from .reference import CITIES, CITY_ALIASES, COUNTRIES, LEGAL_TOKENS, NAME_ABBREVIATIONS, VALID_CURRENCIES

DOMAINS = ("city", "name_token", "currency")
DROP = "<LEGAL_FORM>"  # name_token target meaning "this token is a (misspelt) legal form: drop it"
MAPPING_COLUMNS = ["domain", "raw_value", "canonical", "source", "confidence", "status", "model", "run_id",
                   "created_at"]


def canonical_cities() -> list[str]:
    return sorted({canonical for cities in CITIES.values() for canonical, _ in cities})


def name_tokens(name: str | None) -> list[str]:
    """Upper-case tokens of a vendor name with punctuation and legal forms removed (no mappings applied)."""
    if not isinstance(name, str) or not name:
        return []
    s = re.sub(r"[^A-Z0-9 ]", " ", name.upper().replace(".", ""))
    return [t for t in s.split() if t not in LEGAL_TOKENS]


@dataclass
class Mappings:
    """Value mappings applied during standardization. Keys are upper-case raw values."""
    city: dict[str, str] = field(default_factory=dict)
    name_token: dict[str, str] = field(default_factory=dict)
    currency: dict[str, str] = field(default_factory=dict)

    @classmethod
    def seed(cls) -> "Mappings":
        """What the platform knows before learning: canonical city names only, no aliases or abbreviations."""
        return cls(city={c.upper(): c for c in canonical_cities()}, name_token={},
                   currency={c: c for c in VALID_CURRENCIES})

    @classmethod
    def reference(cls) -> "Mappings":
        """The full hand-curated reference (used by the lightweight CSV pipeline and unit tests)."""
        return cls(city=dict(CITY_ALIASES), name_token=dict(NAME_ABBREVIATIONS),
                   currency={c: c for c in VALID_CURRENCIES})

    @classmethod
    def from_table(cls, df: pd.DataFrame) -> "Mappings":
        m = cls.seed()
        if df is None or df.empty:
            return m
        latest = df.sort_values("created_at").drop_duplicates(["domain", "raw_value"], keep="last")
        for row in latest[latest["status"] == "approved"].itertuples():
            getattr(m, row.domain)[row.raw_value] = row.canonical
        return m

    def known(self, domain: str) -> set[str]:
        return set(getattr(self, domain))


def unmapped_cities(raw_cities: pd.Series, mappings: Mappings, decided: set[str]) -> list[str]:
    values = {v.strip().upper() for v in raw_cities.dropna() if isinstance(v, str) and v.strip()}
    return sorted(values - mappings.known("city") - decided)


def token_vocabulary(names: pd.Series, mappings: Mappings) -> tuple[set[str], list[str]]:
    """Core vocabulary (frequent tokens) and rare tokens that may be abbreviations or typos."""
    counts = Counter(t for n in names for t in name_tokens(n))
    core_min = max(3, min(20, len(names) // 300))
    core = {t for t, c in counts.items() if c >= core_min}
    rare = sorted(t for t in counts if t not in core and t not in mappings.name_token and not t.isdigit())
    return core, rare


def validate(domain: str, raw: str, canonical: str | None, core_tokens: set[str]) -> str | None:
    """Guardrail on an authored mapping: the target must already be a known canonical value."""
    if not canonical:
        return "no canonical value proposed"
    if domain == "currency" and canonical not in VALID_CURRENCIES:
        return f"{canonical!r} is not a supported currency"
    if domain == "city" and canonical not in canonical_cities():
        return f"{canonical!r} is not a known city"
    if domain == "name_token" and canonical == DROP:
        return None
    if domain == "name_token":
        if canonical not in core_tokens:
            return f"{canonical!r} is not in the core name vocabulary"
        if canonical == raw or canonical[0] != raw[0]:
            return "expansion must differ from the token and share its first letter"
    return None


def mapping_rows(domain: str, decisions: list[dict], source: str, model: str, run_id: str,
                 auto_approve_at: float = 0.9) -> pd.DataFrame:
    now = datetime.now(timezone.utc)
    rows = [{"domain": domain, "raw_value": d["raw"], "canonical": d.get("canonical"), "source": source,
             "confidence": float(d.get("confidence", 0.0)),
             "status": d.get("status") or ("approved" if d.get("confidence", 0) >= auto_approve_at else "pending"),
             "model": model, "run_id": run_id, "created_at": now} for d in decisions]
    return pd.DataFrame(rows, columns=MAPPING_COLUMNS)


def country_names() -> dict[str, str]:
    return {iso2: name for iso2, (name, *_rest) in COUNTRIES.items()}
