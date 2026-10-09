"""Apply approved record fixes from the rule library, recording which library item changed each record."""
from __future__ import annotations

import pandas as pd

from .reference import COUNTRIES


def apply_record_fixes(invoices: pd.DataFrame, vendors: pd.DataFrame, fixes: list[dict]) -> pd.DataFrame:
    out = invoices.copy()
    out["fixed_by"] = None
    if not fixes:
        return out
    country = dict(zip(vendors["record_key"], vendors["country_iso2"]))
    raw = out["currency_raw"].map(lambda v: v.strip().upper() if isinstance(v, str) and v.strip() else "(blank)")
    for fix in fixes:
        if fix["fix"] != "currency_from_vendor_country":
            continue
        hit = (out["source_system"] == fix["source_system"]) & (raw == fix["currency_raw"])
        inferred = out.loc[hit, "vendor_record_key"].map(country).map(
            lambda c: COUNTRIES[c][3] if c in COUNTRIES else None)
        ok = inferred.notna()
        idx = inferred[ok].index
        out.loc[idx, "currency"] = inferred[ok]
        out.loc[idx, "fixed_by"] = fix["item_id"]
    return out
