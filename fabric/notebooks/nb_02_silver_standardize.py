# Fabric notebook: nb_02_silver_standardize  (PySpark + pandas)
# Requires the goldenrecord wheel in the attached Fabric Environment (see fabric/README.md).
# Maps the three ERP schemas to one canonical model, runs the DQ rules, and writes a run-metrics
# row that Fabric Activator watches.

# %% Parameters
sources = ["ERP_A", "ERP_B", "ERP_C"]

# %% Standardize
import pandas as pd
from pyspark.sql import functions as F

from goldenrecord.standardize import standardize_invoices, standardize_vendors

drop = ["_source_system", "_source_file", "_ingested_at"]
vendors = pd.concat([standardize_vendors(spark.table(f"bronze_{s.lower()}_vendors").drop(*drop).toPandas(), s)
                     for s in sources], ignore_index=True)
invoices = pd.concat([standardize_invoices(spark.table(f"bronze_{s.lower()}_invoices").drop(*drop).toPandas(), s)
                      for s in sources], ignore_index=True)

spark.createDataFrame(vendors).write.mode("overwrite").format("delta").saveAsTable("silver_vendor")
spark.createDataFrame(invoices).write.mode("overwrite").format("delta").saveAsTable("silver_invoice")

# %% Local DQ rules (the same rules are configured in Purview on these Silver tables)
from goldenrecord.rules import detect_amount_anomalies, load_rules, run_rules

rules = load_rules("/lakehouse/default/Files/config/dq_rules.yaml")
failures, scorecard = run_rules(vendors, invoices, rules)
flags = pd.concat([failures, detect_amount_anomalies(invoices)], ignore_index=True)
spark.createDataFrame(flags).write.mode("overwrite").format("delta").saveAsTable("silver_dq_failures")
spark.createDataFrame(scorecard).write.mode("overwrite").format("delta").saveAsTable("dq_scorecard")

# %% Run metrics for Fabric Activator (append-only)
failing = set(flags["record_key"])
all_keys = pd.concat([vendors["record_key"], invoices["record_key"]])
metrics = pd.DataFrame([{
    "run_at": pd.Timestamp.utcnow(),
    "records": len(all_keys),
    "pass_rate": float((~all_keys.isin(failing)).mean()),
    "anomalies": int((flags["rule_id"] == "A01").sum()),
    "worst_rule": scorecard.sort_values("pass_rate").iloc[0]["rule_id"],
    "worst_rule_pass_rate": float(scorecard["pass_rate"].min()),
}])
spark.createDataFrame(metrics).write.mode("append").format("delta").saveAsTable("dq_run_metrics")
display(metrics)
