"""Pattern-level steward queue: group every open issue by root cause and propose one fix per group.

A steward approves "set currency from the vendor's country for 812 ERP_B invoices" once, instead of
reviewing 812 records. Approval turns the proposed item into a versioned rule-library entry
(library.py) that also applies to every future record with the same root cause.
"""
from __future__ import annotations

import hashlib
import json

import pandas as pd

from .matching import evidence_signature

PATTERN_COLUMNS = ["pattern_id", "kind", "title", "rule_id", "source_system", "signature", "affected_records",
                   "proposed_item", "options", "sample_keys", "evidence", "proposed_by", "confidence", "needs_input"]


def _pid(item_id: str) -> str:
    return "P-" + hashlib.sha1(item_id.encode()).hexdigest()[:10]


def _shape(value) -> str:
    import re
    if value is None:
        return "(blank)"
    return re.sub(r"[0-9]", "9", re.sub(r"[A-Za-z]", "A", str(value)))[:16]


def failure_signature(rule_id: str, row: dict) -> str:
    """Plain-English root cause of a rule failure, coarse enough that one fix covers the group."""
    if rule_id == "R01":
        return "tax ID missing"
    if rule_id == "R02":
        tax = row.get("tax_id") or ""
        return "tax ID too short" if len(tax) < 12 else "tax ID too long" if len(tax) > 12 else "tax ID bad characters"
    if rule_id == "R03":
        return f"country '{row.get('country_raw') or '(blank)'}'"
    if rule_id == "R04":
        return "email without a valid domain"
    if rule_id == "R05":
        return "amount missing" if row.get("amount") is None or pd.isna(row.get("amount")) else "amount zero or negative"
    if rule_id == "R06":
        return "date unparseable" if row.get("invoice_date") is None else "date in the future"
    if rule_id == "R07":
        raw = row.get("currency_raw")
        return f"currency '{raw.strip().upper() if isinstance(raw, str) and raw.strip() else '(blank)'}'"
    if rule_id == "R08":
        return "vendor ID not in vendor master"
    if rule_id == "R09":
        return "duplicate invoice number"
    if rule_id == "A01":
        return "amount over 20x the vendor's median"
    return "fails custom rule"


def _row(**kw) -> dict:
    return {c: kw.get(c) for c in PATTERN_COLUMNS}


def dq_patterns(flags: pd.DataFrame, vendors: pd.DataFrame, invoices: pd.DataFrame, rules: list[dict],
                acknowledged: set[str], enforced: set[str]) -> pd.DataFrame:
    names = {r["id"]: r["name"] for r in rules}
    names["A01"] = "Invoice amount is not an outlier"
    records = pd.concat([vendors.assign(_entity="vendor"), invoices.assign(_entity="invoice")], ignore_index=True)
    records = records.drop_duplicates("record_key")
    lookup = records.set_index("record_key").to_dict("index") if not records.empty else {}
    f = flags[flags["rule_id"].isin(enforced)].copy()
    if f.empty:
        return pd.DataFrame(columns=PATTERN_COLUMNS)
    f["source_system"] = f["record_key"].str.split(":").str[0]
    f["signature"] = [failure_signature(r, lookup.get(k, {})) for r, k in zip(f["rule_id"], f["record_key"])]
    fixable = (f["rule_id"] == "R07") & (f["signature"] != "currency 'XXX'")
    # Fixes are scoped to one source; acknowledgements group the same root cause across all sources.
    f.loc[~fixable, "source_system"] = "*"
    out = []
    for (rule_id, source, sig), g in f.groupby(["rule_id", "source_system", "signature"]):
        keys = g["record_key"].unique().tolist()
        ack_id = f"ACK:{rule_id}:{source}:{sig}"
        if ack_id in acknowledged:
            continue
        if rule_id == "R07" and sig != "currency 'XXX'":
            item = {"item_id": f"FIX:R07:{source}:{sig}", "kind": "record_fix", "definition": {
                "fix": "currency_from_vendor_country", "source_system": source,
                "currency_raw": sig.split("'")[1]}, "affected_records": len(keys), "source": "rule"}
            title = f"{source}: {len(keys):,} invoices with {sig}. Fix: use the vendor's country currency"
            proposed_by, conf = "rule", 0.8
        else:
            item = {"item_id": ack_id, "kind": "acknowledge", "definition": {
                "rule_id": rule_id, "source_system": source, "signature": sig}, "affected_records": len(keys)}
            sources = sorted({k.split(":")[0] for k in keys})
            entity = next((r["entity"] for r in rules if r["id"] == rule_id), "invoice")
            action = ("Keep quarantined" if entity == "invoice" else
                      "Keep flagged (vendor still matched; the bad value is ignored)")
            title = (f"{len(keys):,} records fail {rule_id} ({names.get(rule_id, rule_id)}): {sig} "
                     f"[{', '.join(sources)}]. {action}; notify each source's data owner")
            proposed_by, conf = "rule", 1.0
        out.append(_row(pattern_id=_pid(item["item_id"]), kind=item["kind"], title=title, rule_id=rule_id,
                        source_system=source, signature=sig, affected_records=len(keys),
                        proposed_item=json.dumps(item), options=None, sample_keys=json.dumps(keys[:5]),
                        evidence=names.get(rule_id, rule_id), proposed_by=proposed_by, confidence=conf,
                        needs_input=False))
    return pd.DataFrame(out, columns=PATTERN_COLUMNS)


def match_patterns(pairs: pd.DataFrame) -> pd.DataFrame:
    """MEDIUM pairs grouped by evidence signature: approve 'merge every pair with this evidence' once."""
    open_pairs = pairs[(pairs["band"] == "MEDIUM")]
    if open_pairs.empty:
        return pd.DataFrame(columns=PATTERN_COLUMNS)
    sigs = [evidence_signature(r) for r in open_pairs.to_dict("records")]
    open_pairs = open_pairs.assign(signature=sigs)
    out = []
    for sig, g in open_pairs.groupby("signature"):
        ai = g["ai_decision"].dropna() if "ai_decision" in g else pd.Series(dtype=object)
        same_share = float((ai == "same").mean()) if len(ai) else None
        decision = "match" if (same_share if same_share is not None else g["score"].mean() >= 0.8) else "no_match"
        if same_share is not None:
            decision = "match" if same_share >= 0.5 else "no_match"
        item = {"item_id": f"MATCH:{sig}", "kind": "match_rule", "definition": {"signature": sig, "decision": decision},
                "affected_records": len(g), "source": "llm" if same_share is not None else "rule"}
        examples = "; ".join(f"{a} ~ {b}" for a, b in zip(g["left_name"].head(3), g["right_name"].head(3)))
        title = (f"{len(g):,} vendor pairs with evidence [{sig}]. Proposed: "
                 f"{'merge all' if decision == 'match' else 'keep all separate'}")
        out.append(_row(pattern_id=_pid(item["item_id"]), kind="match_rule", title=title, rule_id=None,
                        source_system=None, signature=sig, affected_records=len(g), proposed_item=json.dumps(item),
                        options=None, sample_keys=json.dumps(list(zip(g["left_key"].head(5), g["right_key"].head(5)))),
                        evidence=f"avg score {g['score'].mean():.2f}; e.g. {examples}",
                        proposed_by=item["source"],
                        confidence=round(same_share if same_share is not None else float(g["score"].mean()), 3),
                        needs_input=False))
    return pd.DataFrame(out, columns=PATTERN_COLUMNS)


def mapping_patterns(proposals: list[dict]) -> pd.DataFrame:
    """Value mappings the AI or rules were not confident enough to auto-approve.

    Validated proposals are bundled per domain into one bulk pattern ("approve 160 typo corrections");
    values with no valid proposal become one pattern each, asking the steward for the canonical value.
    Unknown currency codes without a proposal are left to the R07 pattern, which proposes a fix.
    """
    out = []
    with_target = pd.DataFrame([p for p in proposals if p.get("canonical")])
    if not with_target.empty:  # confident and uncertain proposals are reviewed as separate bundles
        with_target["band"] = with_target["confidence"].map(lambda c: "confident" if c >= 0.75 else "uncertain")
    groups = with_target.groupby(["domain", "source", "band"]) if not with_target.empty else []
    for (domain, source, band), group in groups:
        items = [{"item_id": f"MAP:{domain}:{r.raw}", "kind": "value_mapping", "source": source,
                  "confidence": float(r.confidence), "affected_records": int(r.affected),
                  "definition": {"domain": domain, "raw_value": r.raw, "canonical": r.canonical}}
                 for r in group.itertuples()]
        batch_id = f"BATCH:{domain}:{source}:{band}"
        affected = int(group["affected"].sum())
        preview = "; ".join(f"{r.raw}->{r.canonical}" for r in group.head(6).itertuples())
        title = (f"{len(items)} {domain.replace('_', ' ')} mappings proposed by {source} "
                 f"(confidence {group['confidence'].min():.2f}-{group['confidence'].max():.2f}) "
                 f"covering {affected:,} records. Approve all")
        out.append(_row(pattern_id=_pid(batch_id + ":" + ",".join(sorted(group["raw"]))), kind="mapping_batch",
                        title=title, rule_id=None, source_system=None, signature=batch_id, affected_records=affected,
                        proposed_item=json.dumps({"item_id": batch_id, "kind": "mapping_batch", "items": items}),
                        options=None, sample_keys=json.dumps([]), evidence=preview, proposed_by=source,
                        confidence=round(float(group["confidence"].mean()), 3), needs_input=False))
    tail = [p for p in proposals if not p.get("canonical") and p["domain"] != "currency" and p["affected"] < 5]
    if tail:
        items = [{"item_id": f"MAP:{p['domain']}:{p['raw']}", "kind": "value_mapping", "source": "steward",
                  "confidence": 1.0, "affected_records": p["affected"],
                  "definition": {"domain": p["domain"], "raw_value": p["raw"], "canonical": p["raw"]}} for p in tail]
        affected = sum(p["affected"] for p in tail)
        out.append(_row(pattern_id=_pid("TAIL:" + ",".join(sorted(p["raw"] for p in tail))), kind="mapping_batch",
                        title=f"{len(tail)} rare values with no confident correction (under 5 records each, "
                              f"{affected} records). Keep them as they are",
                        rule_id=None, source_system=None, signature="TAIL", affected_records=affected,
                        proposed_item=json.dumps({"item_id": "TAIL", "kind": "mapping_batch", "items": items}),
                        options=None, sample_keys=json.dumps([]),
                        evidence=", ".join(p["raw"] for p in tail[:12]), proposed_by="rule", confidence=1.0,
                        needs_input=False))
    for p in proposals:
        if p.get("canonical") or p["domain"] == "currency" or p["affected"] < 5:
            continue
        item = {"item_id": f"MAP:{p['domain']}:{p['raw']}", "kind": "value_mapping", "affected_records": p["affected"],
                "source": "steward", "confidence": 1.0,
                "definition": {"domain": p["domain"], "raw_value": p["raw"], "canonical": None}}
        title = f"{p['affected']:,} records with {p['domain'].replace('_', ' ')} '{p['raw']}'. Choose the canonical value"
        out.append(_row(pattern_id=_pid(item["item_id"]), kind="value_mapping", title=title, rule_id=None,
                        source_system=None, signature=f"{p['domain']}:{p['raw']}", affected_records=p["affected"],
                        proposed_item=json.dumps(item), options=json.dumps(p.get("options", [])),
                        sample_keys=json.dumps([]), evidence=p.get("reason", ""), proposed_by="none",
                        confidence=0.0, needs_input=True))
    return pd.DataFrame(out, columns=PATTERN_COLUMNS)


def coverage(patterns: pd.DataFrame, top: int = 10) -> dict:
    if patterns.empty:
        return {"open_patterns": 0, "issues_in_patterns": 0, f"top{top}_coverage": 1.0}
    counts = patterns["affected_records"].sort_values(ascending=False)
    total = int(counts.sum())
    return {"open_patterns": len(patterns), "issues_in_patterns": total,
            f"top{top}_coverage": round(float(counts.head(top).sum() / total), 4) if total else 1.0}
