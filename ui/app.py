"""GoldenRecord dev harness UI (Streamlit). OFFLINE DEVELOPMENT ONLY.

In Fabric these screens are Power BI reports and the actions are translytical task flows calling
User Data Functions (fabric/functions/). This harness lets the team build and rehearse without Fabric.
"""
from __future__ import annotations

import json
import os

import pandas as pd
import requests
import streamlit as st

from goldenrecord.store import Lakehouse

API = os.environ.get("API_URL", "http://localhost:8000")
st.set_page_config(page_title="GoldenRecord", page_icon="🟡", layout="wide")
lake = Lakehouse()


@st.cache_data(ttl=5)
def table(name: str) -> pd.DataFrame:
    return lake.read(name)


def call(method: str, path: str, **kwargs):
    try:
        r = requests.request(method, f"{API}{path}", timeout=600, **kwargs)
        if r.status_code >= 400:
            st.error(f"{r.status_code}: {r.json().get('detail', r.text)}")
            return None
        st.cache_data.clear()
        return r.json()
    except requests.RequestException as exc:
        st.error(f"Agent API unreachable at {API}: {exc}")
        return None


def pct(x) -> str:
    return "–" if x is None or pd.isna(x) else f"{x:.1%}"


st.sidebar.title("GoldenRecord")
st.sidebar.caption("Dev harness · in Fabric this is Power BI + translytical task flows")
page = st.sidebar.radio("View", ["Overview", "Pattern queue", "Golden records", "Rule studio", "Rule library",
                                 "Executive spend", "Alerts & agents"])
reviewer = st.sidebar.text_input("Steward", value="steward")
try:
    health = requests.get(f"{API}/health", timeout=5).json()
    st.sidebar.success(f"API up · LLM: {health['llm']}")
except requests.RequestException:
    st.sidebar.error("Agent API not reachable")

runs = table("run_history")
latest = runs.sort_values("run_at").iloc[-1] if not runs.empty else None

if page == "Overview":
    st.title("Overview")
    if latest is None:
        st.info("No run yet. The API bootstraps one on first start, or press Run pipeline.")
    else:
        c = st.columns(5)
        c[0].metric("DQ score Silver → Gold", pct(latest["dq_score_after"]), f"from {pct(latest['dq_score_before'])}")
        c[1].metric("Open issues", f"{int(latest['issue_records']):,}",
                    f"in {int(latest['open_patterns'])} patterns", delta_color="off")
        c[2].metric("Records repaired", f"{int(latest['records_fixed']):,}")
        c[3].metric("Golden vendors", f"{int(latest['golden_vendors']):,}",
                    f"{int(latest['suspect_golden_records'])} suspect", delta_color="inverse")
        c[4].metric("Rule library", f"v{int(latest['library_version'])}",
                    f"{int(latest['llm_calls'])} LLM calls this run", delta_color="off")
        if pd.notna(latest.get("match_precision")):
            st.caption(f"Against seeded ground truth: match precision {pct(latest['match_precision'])}, recall "
                       f"{pct(latest['match_recall'])}, defect catch rate {pct(latest['catch_rate'])}.")
    b = st.columns(3)
    if b[0].button("▶ Run pipeline", type="primary"):
        with st.spinner("Ingest → learn → Silver → Quality → Matcher → Gatekeeper → Steward → Sentinel"):
            res = call("POST", "/runs")
        if res:
            st.success(f"Run {res['summary']['run_id']} finished in {res['summary']['seconds']}s")
    if b[1].button("Inject bad batch (demo)"):
        if call("POST", "/demo/bad-batch"):
            st.warning("3,000 broken ERP_A invoices staged. Run the pipeline to see the Sentinel react.")
    if b[2].button("Remove bad batch"):
        call("DELETE", "/demo/bad-batch")
    if not runs.empty:
        st.subheader("Run history")
        st.dataframe(runs.sort_values("run_at", ascending=False)[
            ["run_at", "library_version", "llm_calls", "issue_records", "open_patterns", "records_fixed",
             "golden_vendors", "dq_score_after", "alerts"]], hide_index=True, width="stretch")

elif page == "Pattern queue":
    st.title("Pattern queue")
    pats = table("steward_patterns")
    if pats.empty:
        st.success("No open patterns.")
    else:
        st.caption(f"{int(pats['affected_records'].sum()):,} affected records in {len(pats)} root-cause patterns. "
                   "One decision applies to every record in the pattern, now and on future loads.")
        for p in pats.head(25).itertuples():
            with st.expander(f"{p.affected_records:,} records · {p.kind} · {p.title}"):
                st.write(f"**Evidence:** {p.evidence}  ·  proposed by **{p.proposed_by}**, confidence {p.confidence}")
                canonical = None
                if p.needs_input:
                    canonical = st.selectbox("Canonical value", json.loads(p.options or "[]"), key=f"c{p.pattern_id}")
                c = st.columns(2)
                if c[0].button("✅ Approve for all", key=f"a{p.pattern_id}", type="primary"):
                    res = call("POST", f"/patterns/{p.pattern_id}/decision",
                               json={"decision": "approve", "reviewer": reviewer, "canonical": canonical})
                    if res:
                        st.success(f"Library v{res['library_version']}: {res['item_id']} "
                                   f"({res['affected_records']:,} records, applies from the next run)")
                if c[1].button("Reject", key=f"r{p.pattern_id}"):
                    call("POST", f"/patterns/{p.pattern_id}/decision", json={"decision": "reject", "reviewer": reviewer})

elif page == "Golden records":
    st.title("Golden records")
    alerts = table("gold_cluster_alerts")
    st.subheader(f"Suspect golden records ({len(alerts)})")
    if not alerts.empty:
        st.dataframe(alerts, hide_index=True, width="stretch")
    key = st.text_input("Master key", value=alerts.iloc[0]["master_key"] if not alerts.empty else "GRV-000001")
    if st.button("Explain"):
        st.session_state["explain"] = call("GET", f"/golden/{key}")
    ex = st.session_state.get("explain")
    if ex:
        st.write(f"**{ex['master_key']}** has {len(ex['members'])} members. Suspect: {ex['suspect'] or 'no'}")
        st.dataframe(pd.DataFrame(ex["merges"]), hide_index=True, width="stretch")
        rec = st.selectbox("Detach member", ex["members"])
        if st.button("Unmerge (adds a versioned cannot-link)"):
            res = call("POST", "/golden/unmerge", json={"record_key": rec, "reviewer": reviewer})
            if res:
                st.success(f"Library v{res['library_version']}: {res['cannot_links']} cannot-links; next run separates them")

elif page == "Rule studio":
    st.title("Rule studio")
    st.caption("Plain English → validated rule → impact preview. Rules failing more than 5% of a table are blocked; "
               "accepted rules start in shadow mode (flag, don't quarantine) until promoted.")
    text = st.text_input("Rule", "Invoice amount must not exceed 1,000,000")
    if st.button("Preview impact"):
        st.session_state["draft"] = call("POST", "/rules/draft", json={"text": text})
    d = st.session_state.get("draft")
    if d and d.get("ok"):
        pv = d["preview"]
        (st.error if d["blocked"] else st.info)(d["message"])
        st.json(d["rule"])
        st.write(f"Would fail **{pv['failed']:,}** of {pv['evaluated']:,} ({pv['fail_rate']:.1%}) · by source: {pv['by_source']}")
        override = st.checkbox("Override the blast-radius limit", disabled=not d["blocked"])
        if st.button("Accept in shadow mode"):
            res = call("POST", "/rules/draft", json={"text": text, "accept": True, "override": override,
                                                     "reviewer": reviewer})
            if res and res.get("saved"):
                st.success(f"Rule {res['rule']['id']} added to library v{res['library_version']} in shadow mode")
    elif d:
        st.error(d.get("error"))
    card = table("dq_scorecard")
    shadow = card[card.get("mode", pd.Series(dtype=str)) == "shadow"] if not card.empty else card
    for r in shadow.itertuples():
        if st.button(f"Promote {r.rule_id} to enforce (would quarantine {r.failed:,})"):
            call("POST", f"/rules/{r.rule_id}/promote", json={"reviewer": reviewer})

elif page == "Rule library":
    st.title("Rule library")
    hist = table("rule_library")
    if hist.empty:
        st.info("Empty: approvals and auto-approved mappings appear here, versioned.")
    else:
        st.caption(f"Version {int(hist['library_version'].max())} · {hist['item_id'].nunique()} items. "
                   "Append-only: retiring an item adds a new version.")
        st.dataframe(hist.sort_values("library_version", ascending=False), hide_index=True, width="stretch")
        item = st.selectbox("Retire item", sorted(hist["item_id"].unique()))
        if st.button("Retire"):
            res = call("POST", f"/library/{item}/retire", json={"reviewer": reviewer})
            if res:
                st.success(f"Retired in library v{res['library_version']}")

elif page == "Executive spend":
    st.title("Executive spend")
    st.caption("Reads only Gold: golden vendors and invoices that passed every enforced rule.")
    spend, vendors = table("gold_spend_fact"), table("gold_vendor")
    if spend.empty:
        st.info("No Gold data yet.")
    else:
        spend = spend.merge(vendors[["master_key", "vendor_name", "country_iso2"]], on="master_key")
        c = st.columns(3)
        c[0].metric("Total spend (USD)", f"${spend['amount_usd'].sum() / 1e6:,.1f}M")
        c[1].metric("Invoices", f"{len(spend):,}")
        c[2].metric("Vendors in 2+ ERPs", f"{int((vendors['member_count'] > 1).sum()):,}")
        st.bar_chart(spend.groupby("vendor_name")["amount_usd"].sum().nlargest(10).sort_values(), horizontal=True)
        st.line_chart(spend.groupby(pd.to_datetime(spend["invoice_date"]).dt.to_period("M").astype(str))["amount_usd"].sum())

else:
    st.title("Alerts & agents")
    alerts = table("alerts")
    st.dataframe(alerts.sort_values("raised_at", ascending=False) if not alerts.empty else alerts,
                 hide_index=True, width="stretch")
    scores = table("dq_source_score_history")
    if not scores.empty:
        st.subheader("Quality score per source (Activator watches this)")
        st.line_chart(scores.pivot_table(index="scored_at", columns="source_system", values="dq_score"))
    events = table("agent_events")
    if not events.empty:
        st.subheader("Agent audit trail")
        st.dataframe(events.sort_values("logged_at", ascending=False).head(100), hide_index=True, width="stretch")
