"""GoldenRecord control room (Streamlit): the local stand-in for the Power BI reports and the steward
write-back app. Reads the lakehouse directly; every action goes through the agent API."""
from __future__ import annotations

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
st.sidebar.caption("AI data-quality gatekeeper · local stack")
page = st.sidebar.radio("View", ["Overview", "Executive spend", "Review queue", "Rule studio", "Data quality",
                                 "Alerts & agents"])
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
        st.info("No pipeline run yet. The API bootstraps one on first start; or press Run pipeline.")
    else:
        c = st.columns(5)
        c[0].metric("DQ score Silver → Gold", pct(latest["dq_score_after"]),
                    f"from {pct(latest['dq_score_before'])}")
        c[1].metric("Golden vendors", f"{int(latest['golden_vendors']):,}",
                    f"from {int(latest['silver_vendor_records']):,} records", delta_color="off")
        c[2].metric("Pairs awaiting review", int(latest["review_queue"]))
        c[3].metric("Quarantined invoices", f"{int(latest['quarantined_invoices']):,}")
        c[4].metric("Alerts last run", latest["alerts"] or "none")
        if "match_precision" in latest and pd.notna(latest.get("match_precision")):
            st.caption(f"Against seeded ground truth: match precision {pct(latest['match_precision'])}, "
                       f"recall {pct(latest['match_recall'])}, defect catch rate {pct(latest['catch_rate'])}, "
                       f"false quarantine {pct(latest['false_quarantine_rate'])}. LLM: {latest['llm']}.")
    b = st.columns(3)
    if b[0].button("▶ Run pipeline", type="primary"):
        with st.spinner("Agents running: Profiler → Quality → Matcher → Gatekeeper → Sentinel"):
            res = call("POST", "/runs")
        if res:
            st.success(f"Run {res['summary']['run_id']} finished in {res['summary']['seconds']}s")
            st.json(res["agents"], expanded=False)
    if b[1].button("Inject bad batch (demo)"):
        if call("POST", "/demo/bad-batch"):
            st.warning("3,000 broken ERP_A invoices staged. Run the pipeline to see the Sentinel react.")
    if b[2].button("Remove bad batch"):
        call("DELETE", "/demo/bad-batch")
    if not runs.empty:
        st.subheader("Run history")
        st.dataframe(runs.sort_values("run_at", ascending=False)[
            ["run_at", "llm", "golden_vendors", "review_queue", "quarantined_invoices", "dq_score_before",
             "dq_score_after", "alerts"]], hide_index=True, width="stretch")

elif page == "Executive spend":
    st.title("Executive spend")
    st.caption("Certified view: reads only Gold tables (golden vendors + invoices that passed every rule).")
    spend, vendors, xref = table("gold_spend_fact"), table("gold_vendor"), table("gold_vendor_xref")
    if spend.empty:
        st.info("No Gold data yet.")
    else:
        spend = spend.merge(vendors[["master_key", "vendor_name", "country_iso2", "member_count"]], on="master_key")
        c = st.columns(4)
        c[0].metric("Total spend (USD)", f"${spend['amount_usd'].sum() / 1e6:,.1f}M")
        c[1].metric("Invoices", f"{len(spend):,}")
        c[2].metric("Active vendors", f"{spend['master_key'].nunique():,}")
        c[3].metric("Vendors in 2+ ERPs", f"{int((vendors['member_count'] > 1).sum()):,}")
        left, right = st.columns(2)
        top = spend.groupby("vendor_name")["amount_usd"].sum().nlargest(10).sort_values()
        left.subheader("Top 10 vendors")
        left.bar_chart(top, horizontal=True)
        right.subheader("Spend by country")
        right.bar_chart(spend.groupby("country_iso2")["amount_usd"].sum())
        st.subheader("Spend by month")
        months = pd.to_datetime(spend["invoice_date"]).dt.to_period("M").astype(str)
        st.line_chart(spend.groupby(months)["amount_usd"].sum())
        st.subheader("Before and after harmonization")
        frag = xref.groupby("master_key").size().rename("source_ids")
        split = vendors.set_index("master_key").join(frag).query("source_ids > 1")
        st.write(f"**{len(split):,}** real vendors were recorded under **{int(split['source_ids'].sum()):,}** "
                 "different ERP vendor IDs. Without harmonization their spend is split across those IDs.")
        st.dataframe(split.sort_values("source_ids", ascending=False)[
            ["vendor_name", "source_systems", "source_ids", "country_iso2"]].head(20), width="stretch")

elif page == "Review queue":
    st.title("Steward review queue")
    queue = table("review_queue")
    if queue.empty:
        st.success("Nothing to review.")
    else:
        queue = queue.sort_values("score", ascending=False).reset_index(drop=True)
        st.caption(f"{len(queue)} pairs in the MEDIUM band. Each decision is saved as a training label.")
        labels = [f"{r.left_name}  ↔  {r.right_name}  ({r.score:.2f})" for r in queue.itertuples()]
        i = st.selectbox("Pair", range(len(queue)), format_func=lambda k: labels[k])
        pair = queue.iloc[i]
        st.write(f"**Evidence:** {pair['explanation']}")
        reviewer = st.text_input("Reviewer", value=st.session_state.get("reviewer", "steward"))
        st.session_state["reviewer"] = reviewer
        cols = st.columns(4)
        if cols[0].button("Ask the steward assistant"):
            rec = call("POST", "/review/recommend", json={"left_key": pair["left_key"], "right_key": pair["right_key"]})
            if rec:
                st.session_state["rec"] = {**rec, "pair": (pair["left_key"], pair["right_key"])}
        rec = st.session_state.get("rec")
        if rec and tuple(rec["pair"]) == (pair["left_key"], pair["right_key"]):
            st.info(f"**Recommendation: {rec['recommendation']}** — {rec['rationale']}\n\n"
                    f"Check: {rec['what_to_check']}" + ("" if rec["used_llm"] else "  _(rules-only assistant)_"))
            st.dataframe(pd.DataFrame({"A": rec["left"], "B": rec["right"]}).astype(str), width="stretch")
        body = {"left_key": pair["left_key"], "right_key": pair["right_key"], "reviewer": reviewer}
        if cols[1].button("✅ Same vendor", type="primary"):
            if call("POST", "/review/decisions", json={**body, "decision": "match"}):
                st.session_state.pop("rec", None)
                st.success("Saved. It merges on the next run.")
        if cols[2].button("❌ Different vendors"):
            if call("POST", "/review/decisions", json={**body, "decision": "no_match"}):
                st.session_state.pop("rec", None)
                st.success("Saved.")
    st.divider()
    decisions = table("steward_decisions")
    st.write(f"Steward decisions recorded: **{len(decisions)}**")
    if st.button("Train matcher on decisions (MLflow)"):
        res = call("POST", "/learning/train")
        if res:
            (st.success if res.get("ok") else st.warning)(res)

elif page == "Rule studio":
    st.title("Rule studio")
    st.caption("Describe a rule in plain English. The Profiler agent drafts it, checks it against real columns, "
               "and dry-runs it on Silver before you accept it.")
    text = st.text_input("Rule", "Vendor email must not be empty")
    c = st.columns(2)
    if c[0].button("Draft and dry-run"):
        st.session_state["draft"] = call("POST", "/rules/draft", json={"text": text, "accept": False})
    draft = st.session_state.get("draft")
    if draft:
        if draft.get("ok"):
            st.json(draft["rule"])
            st.write(f"Dry run: **{draft['dry_run']['failed']:,}** of {draft['dry_run']['evaluated']:,} records "
                     f"would fail. Sample: {', '.join(draft['sample_failures'])}")
            if c[1].button("Accept rule"):
                res = call("POST", "/rules/draft", json={"text": text, "accept": True})
                if res and res.get("ok"):
                    st.success(f"Rule {res['rule']['id']} saved. It runs from the next pipeline run.")
                    st.session_state.pop("draft", None)
        else:
            st.error(draft.get("error"))
    custom = table("dq_rules_custom")
    if not custom.empty:
        st.subheader("Steward-approved rules")
        st.dataframe(custom, hide_index=True, width="stretch")

elif page == "Data quality":
    st.title("Data quality")
    card = table("dq_scorecard")
    if not card.empty:
        st.subheader("Scorecard (mirrors the Purview data-quality rules)")
        st.dataframe(card, hide_index=True, width="stretch")
        st.bar_chart(card.set_index("rule_id")["pass_rate"])
    q = table("quarantine_invoice")
    if not q.empty:
        st.subheader(f"Quarantined invoices ({len(q):,})")
        st.dataframe(q.head(200), hide_index=True, width="stretch")
    prof = table("dq_profile")
    if not prof.empty:
        st.subheader("Profile (Profiler agent)")
        st.dataframe(prof.drop(columns=["run_id"]), hide_index=True, width="stretch")

else:
    st.title("Alerts & agent activity")
    alerts = table("alerts")
    if alerts.empty:
        st.success("No alerts raised.")
    else:
        st.dataframe(alerts.sort_values("raised_at", ascending=False), hide_index=True, width="stretch")
    events = table("agent_events")
    if not events.empty:
        st.subheader("Agent audit trail")
        st.dataframe(events.sort_values("logged_at", ascending=False).head(100), hide_index=True,
                     width="stretch")
