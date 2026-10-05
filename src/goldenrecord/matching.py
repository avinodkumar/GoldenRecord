"""Candidate generation, pair scoring, confidence bands and clustering.

Locally, name similarity uses fuzzy string matching. In Fabric, nb_03_ai_match adds
ai.similarity and ai.classify on top of these features (see docs/06-matching-design.md).
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from itertools import combinations

import pandas as pd

from .config import AI_MIN_CONFIDENCE, AI_PROMOTE_MIN_SCORE, HIGH_BAND, MEDIUM_BAND, TAX_ID_PATTERN

try:
    from rapidfuzz import fuzz

    def name_similarity(a: str | None, b: str | None) -> float:
        if not a or not b:
            return 0.0
        return fuzz.token_sort_ratio(a, b) / 100.0
except ImportError:  # pragma: no cover - fallback when rapidfuzz is absent
    def name_similarity(a: str | None, b: str | None) -> float:
        if not a or not b:
            return 0.0
        return SequenceMatcher(None, " ".join(sorted(a.split())), " ".join(sorted(b.split()))).ratio()

MAX_BLOCK_SIZE = 60
_TAX_RE = re.compile(TAX_ID_PATTERN)


def _valid_tax(value) -> bool:
    return isinstance(value, str) and bool(_TAX_RE.match(value))


def candidate_pairs(vendors: pd.DataFrame) -> pd.DataFrame:
    """Blocking: only compare records that share a tax ID, a phone, or country + name prefix."""
    v = vendors.copy()
    v["blk_tax"] = v["tax_id"].where(v["tax_id"].map(_valid_tax))
    v["blk_phone"] = v["phone"]
    v["blk_name"] = v["country_iso2"].fillna("??") + "|" + v["vendor_name_norm"].fillna("").str[:4]
    pairs = set()
    for col in ("blk_tax", "blk_phone", "blk_name"):
        for _, keys in v.dropna(subset=[col]).groupby(col)["record_key"]:
            if 2 <= len(keys) <= MAX_BLOCK_SIZE:
                pairs.update(tuple(sorted(p)) for p in combinations(keys, 2))
    return pd.DataFrame(sorted(pairs), columns=["left_key", "right_key"])


def assign_band(score: float) -> str:
    if score >= HIGH_BAND:
        return "HIGH"
    if score >= MEDIUM_BAND:
        return "MEDIUM"
    return "LOW"


def guarded_band(score: float, tax_conflict: bool, ai_decision: str | None = None,
                 ai_confidence: float | None = None) -> str:
    """Final band once the AI has had its say. AI proposes, rules decide (ADR 0002)."""
    if ai_decision is None:
        return assign_band(score)
    confident = ai_confidence is not None and ai_confidence >= AI_MIN_CONFIDENCE
    if ai_decision == "same" and confident and not tax_conflict:
        return "HIGH" if score >= AI_PROMOTE_MIN_SCORE else "MEDIUM"
    if ai_decision == "different" and confident and score < MEDIUM_BAND:
        return "LOW"
    if tax_conflict:
        return "LOW"
    return "MEDIUM" if score >= MEDIUM_BAND or ai_decision == "same" else assign_band(score)


def score_pair(left: dict, right: dict) -> dict:
    """Score one candidate pair and explain the decision in plain English."""
    name_sim = name_similarity(left["vendor_name_norm"], right["vendor_name_norm"])
    lt, rt = left["tax_id"], right["tax_id"]
    tax_eq = _valid_tax(lt) and lt == rt
    tax_conflict = _valid_tax(lt) and _valid_tax(rt) and lt != rt
    city_eq = bool(left["city"]) and left["city"] == right["city"]
    phone_eq = bool(left["phone"]) and left["phone"] == right["phone"]
    domain_eq = bool(left["email_domain"]) and left["email_domain"] == right["email_domain"]

    if tax_eq:
        score = 0.6 + 0.4 * name_sim
    elif tax_conflict:
        score = 0.4 * name_sim
    else:
        score = 0.55 * name_sim + 0.15 * city_eq + 0.15 * phone_eq + 0.15 * domain_eq

    reasons = []
    if tax_eq:
        reasons.append("same tax ID")
    if tax_conflict:
        reasons.append("different valid tax IDs")
    reasons.append(f"name similarity {name_sim:.2f}")
    reasons.append("same city" if city_eq else "different or missing city")
    if phone_eq:
        reasons.append("same phone")
    if domain_eq:
        reasons.append("same email domain")

    score = round(score, 4)
    explanation = "; ".join(reasons)
    return {"name_similarity": round(name_sim, 4), "tax_eq": tax_eq, "tax_conflict": tax_conflict,
            "city_eq": city_eq, "phone_eq": phone_eq, "domain_eq": domain_eq,
            "score": score, "band": assign_band(score), "explanation": explanation[0].upper() + explanation[1:]}


def score_pairs(vendors: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    clean = vendors.astype(object).where(vendors.notna(), None)
    lookup = clean.set_index("record_key").to_dict("index")
    rows = []
    for left_key, right_key in pairs.itertuples(index=False):
        left, right = lookup[left_key], lookup[right_key]
        rows.append({"left_key": left_key, "right_key": right_key,
                     "left_name": left["vendor_name"], "right_name": right["vendor_name"],
                     **score_pair(left, right)})
    cols = ["left_key", "right_key", "left_name", "right_name", "name_similarity", "tax_eq", "tax_conflict",
            "city_eq", "phone_eq", "domain_eq", "score", "band", "explanation"]
    return pd.DataFrame(rows, columns=cols)


def cluster(record_keys, matched_pairs) -> dict[str, str]:
    """Union-find over matched pairs. Returns record_key -> cluster representative."""
    parent = {k: k for k in record_keys}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for a, b in matched_pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    return {k: find(k) for k in record_keys}
