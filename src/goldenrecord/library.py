"""Versioned rule library: how steward and AI decisions become reusable, auditable rules.

Every approved decision is an item in the append-only `rule_library` table:

  kind           item_id example                     what it does on every future run
  value_mapping  MAP:city:BANGALORE                  standardizes a raw value deterministically
  record_fix     FIX:R07:ERP_B:(blank)               repairs a class of failing records (with lineage)
  acknowledge    ACK:R05:ERP_A:amount negative       keeps a known issue quarantined, off the open queue
  match_rule     MATCH:<evidence signature>          merges (or separates) every pair with that evidence
  dq_rule        DQ:C01                              adds a data-quality rule (shadow, then enforce)
  cannot_link    SPLIT:<record A>|<record B>         keeps two records apart forever (undoes a false merge)

Each approval batch increments `library_version`; retiring an item appends a 'retired' row. Runs record
the version they used, so any Gold row can be traced to the exact rules that produced it, and a bad
rule can be rolled back by retiring it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

from .mappings import Mappings

TABLE = "rule_library"
COLUMNS = ["library_version", "item_id", "kind", "definition", "status", "source", "confidence",
           "approved_by", "approved_at", "affected_records", "note", "run_id"]


class RuleLibrary:
    def __init__(self, lake):
        self.lake = lake

    def history(self) -> pd.DataFrame:
        df = self.lake.read(TABLE)
        return df.reindex(columns=COLUMNS) if df.empty else df

    def version(self) -> int:
        h = self.history()
        return 0 if h.empty else int(h["library_version"].max())

    def active(self, kind: str | None = None) -> list[dict]:
        h = self.history()
        if h.empty:
            return []
        latest = h.sort_values("library_version").drop_duplicates("item_id", keep="last")
        latest = latest[latest["status"] == "active"]
        if kind:
            latest = latest[latest["kind"] == kind]
        return [{**r, "definition": json.loads(r["definition"])} for r in latest.to_dict("records")]

    def _append(self, rows: list[dict], status: str, approved_by: str, source: str, run_id: str, note: str) -> int:
        version = self.version() + 1
        now = datetime.now(timezone.utc)
        df = pd.DataFrame([{
            "library_version": version, "item_id": r["item_id"], "kind": r["kind"],
            "definition": json.dumps(r["definition"], sort_keys=True), "status": status,
            "source": r.get("source", source), "confidence": float(r.get("confidence", 1.0)),
            "approved_by": approved_by, "approved_at": now, "affected_records": int(r.get("affected_records", 0)),
            "note": note, "run_id": run_id} for r in rows], columns=COLUMNS)
        self.lake.append(TABLE, df)
        return version

    def approve(self, items: list[dict], approved_by: str, source: str = "steward", run_id: str = "",
                note: str = "") -> int | None:
        return self._append(items, "active", approved_by, source, run_id, note) if items else None

    def retire(self, item_id: str, by: str, note: str = "") -> int:
        current = [i for i in self.active() if i["item_id"] == item_id]
        if not current:
            raise KeyError(f"{item_id} is not active")
        return self._append(current, "retired", by, current[0]["source"], "", note)

    # --- typed views used by the pipeline -------------------------------------------------------
    def mappings(self) -> Mappings:
        m = Mappings.seed()
        for item in self.active("value_mapping"):
            d = item["definition"]
            getattr(m, d["domain"])[d["raw_value"]] = d["canonical"]
        return m

    def match_rules(self) -> dict[str, tuple[str, str]]:
        """evidence signature -> (decision, item_id)"""
        return {i["definition"]["signature"]: (i["definition"]["decision"], i["item_id"])
                for i in self.active("match_rule")}

    def record_fixes(self) -> list[dict]:
        return [{**i["definition"], "item_id": i["item_id"]} for i in self.active("record_fix")]

    def acknowledged(self) -> set[str]:
        return {i["item_id"] for i in self.active("acknowledge")}

    def cannot_links(self) -> list[tuple[str, str, str]]:
        return [(i["definition"]["left_key"], i["definition"]["right_key"], i["item_id"])
                for i in self.active("cannot_link")]

    def dq_rules(self) -> list[dict]:
        return [i["definition"] for i in self.active("dq_rule")]


def mapping_item(domain: str, raw: str, canonical: str, confidence: float, affected: int, source: str) -> dict:
    return {"item_id": f"MAP:{domain}:{raw}", "kind": "value_mapping", "source": source, "confidence": confidence,
            "affected_records": affected, "definition": {"domain": domain, "raw_value": raw, "canonical": canonical}}
