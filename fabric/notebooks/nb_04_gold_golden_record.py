# Fabric notebook: nb_04_gold_golden_record  (pandas)
# Deliverables 1 and 6: golden-record table with survivorship and a stable master key, and the
# governed spend fact that the certified semantic model reads.

# %% Imports and inputs
import pandas as pd

from goldenrecord import config
from goldenrecord.matching import cluster
from goldenrecord.pipeline import BLOCKING_INVOICE_RULES, resolve_matches
from goldenrecord.survivorship import build_golden

vendors = spark.table("silver_vendor").toPandas()
invoices = spark.table("silver_invoice").toPandas()
pairs = spark.table("silver_match_pairs").toPandas()
flags = spark.table("silver_dq_failures").toPandas()

# Steward decisions written back from the Power BI review report (see powerbi/README.md).
decisions = (spark.table("steward_decisions").toPandas() if spark.catalog.tableExists("steward_decisions")
             else pd.DataFrame(columns=["left_key", "right_key", "decision"]))
previous_xref = spark.table("gold_vendor_xref").toPandas() if spark.catalog.tableExists("gold_vendor_xref") else None

# %% Resolve matches, cluster, apply survivorship
matched, review_queue = resolve_matches(pairs, decisions)
clusters = cluster(vendors["record_key"], matched)
gold_vendor, xref = build_golden(vendors, clusters, previous_xref)

# %% Governed spend: only invoices that pass every blocking rule
blocked = flags[flags["rule_id"].isin(BLOCKING_INVOICE_RULES)]
reasons = blocked.groupby("record_key")["rule_id"].agg(lambda r: ",".join(sorted(set(r))))
quarantine = invoices[invoices["record_key"].isin(reasons.index)].assign(
    failed_rules=lambda d: d["record_key"].map(reasons))
clean = invoices[~invoices["record_key"].isin(reasons.index)]
spend = clean.merge(xref[["record_key", "master_key"]].rename(columns={"record_key": "vendor_record_key"}),
                    on="vendor_record_key")
spend["amount_usd"] = (spend["amount"] * spend["currency"].map(config.FX_TO_USD)).round(2)

# %% Write Gold
for name, df in {"gold_vendor": gold_vendor, "gold_vendor_xref": xref, "gold_spend_fact": spend,
                 "review_queue": review_queue, "quarantine_invoice": quarantine}.items():
    spark.createDataFrame(df.astype({c: str for c in df.columns if df[c].dtype == object})) \
        .write.mode("overwrite").option("overwriteSchema", True).format("delta").saveAsTable(name)
    print(f"{name}: {len(df)} rows")
