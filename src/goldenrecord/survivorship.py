"""Gold layer: golden records, stable master keys and survivorship rules."""
from __future__ import annotations

import re
from collections import Counter

import pandas as pd

from .config import EMAIL_PATTERN, SOURCE_PRIORITY, TAX_ID_PATTERN

_TAX_RE = re.compile(TAX_ID_PATTERN)
_EMAIL_RE = re.compile(EMAIL_PATTERN)
KEY_PREFIX = "GRV-"


def _mode(values):
    values = [v for v in values if v]
    if not values:
        return None
    return Counter(values).most_common(1)[0][0]


def _first(values, valid=lambda v: bool(v)):
    return next((v for v in values if v and valid(v)), None)


def assign_master_keys(clusters: dict[str, str], previous_xref: pd.DataFrame | None) -> dict[str, str]:
    """Map cluster id -> master key, reusing keys from the previous run so they stay stable."""
    prev = {} if previous_xref is None else dict(zip(previous_xref["record_key"], previous_xref["master_key"]))
    members: dict[str, list[str]] = {}
    for key, cid in clusters.items():
        members.setdefault(cid, []).append(key)

    used, result = set(), {}
    next_seq = 1 + max((int(k[len(KEY_PREFIX):]) for k in prev.values()), default=0)
    # Largest clusters claim existing keys first, so a split keeps the key on the bigger side.
    for cid in sorted(members, key=lambda c: (-len(members[c]), c)):
        candidates = Counter(prev[k] for k in members[cid] if k in prev and prev[k] not in used)
        if candidates:
            key = sorted(candidates.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        else:
            key = f"{KEY_PREFIX}{next_seq:06d}"
            next_seq += 1
        used.add(key)
        result[cid] = key
    return result


def build_golden(vendors: pd.DataFrame, clusters: dict[str, str],
                 previous_xref: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (gold_vendor, vendor_xref)."""
    master = assign_master_keys(clusters, previous_xref)
    v = vendors.astype(object).where(vendors.notna(), None)
    v["master_key"] = v["record_key"].map(lambda k: master[clusters[k]])
    v["_priority"] = v["source_system"].map(SOURCE_PRIORITY)
    v = v.sort_values(["master_key", "_priority", "record_key"])

    golden = []
    for key, g in v.groupby("master_key", sort=True):
        # The name most sources agree on wins, so one source's typo cannot become the golden name.
        name_norm = _mode(g["vendor_name_norm"])
        golden.append({
            "master_key": key,
            "vendor_name": _first(g.loc[g["vendor_name_norm"] == name_norm, "vendor_name"]),
            "vendor_name_norm": name_norm,
            "tax_id": _mode([t for t in g["tax_id"] if t and _TAX_RE.match(t)]),
            "country_iso2": _mode(g["country_iso2"]),
            "city": _mode(g["city"]),
            "street": _first(g["street"]),
            "phone": _mode(g["phone"]),
            "email": _first(g["email"], lambda e: bool(_EMAIL_RE.match(e))),
            "bank_account": _first(g["bank_account"]),
            "source_systems": ",".join(sorted(g["source_system"].unique())),
            "member_count": len(g),
        })
    xref = v[["master_key", "record_key", "source_system", "source_vendor_id"]].reset_index(drop=True)
    return pd.DataFrame(golden), xref
