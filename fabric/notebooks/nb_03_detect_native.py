# Fabric notebook: nb_03_detect_native  (pipeline step 3): detection with native Fabric features
#   * SynapseML Isolation Forest scores every invoice (multivariate outlier score, shown to stewards)
#   * the deterministic A01 outlier rule (same as the local engine) gates Gold
#   * materialized lake views enforce the rule catalog with CONSTRAINT ... ON MISMATCH DROP; the
#     quarantine view keeps every dropped row WITH the rules it failed (native MLVs only count drops)
# The MLV SQL is generated from config/dq_rules.yaml plus enforced rules in the rule library, so Purview,
# the MLVs and the tested local engine all apply the same rules.

# %% Anomaly scores
import numpy as np
import pandas as pd
from pyspark.ml import Pipeline
from pyspark.ml.feature import VectorAssembler
from pyspark.sql import functions as F
from synapse.ml.isolationforest import IsolationForest

from goldenrecord import config
from goldenrecord.fabric_runtime import FabricLakehouse
from goldenrecord.rules import detect_amount_anomalies

lake = FabricLakehouse(spark)
invoices = lake.read("silver_invoice")
a01 = set(detect_amount_anomalies(invoices)["record_key"])

valid = invoices[invoices["amount"].notna() & (invoices["amount"] > 0)].copy()
valid["log_amount"] = np.log1p(valid["amount"])
valid["vendor_ratio"] = valid["amount"] / valid.groupby("vendor_record_key")["amount"].transform("median")
features = spark.createDataFrame(valid[["record_key", "log_amount", "vendor_ratio"]])
iforest = (IsolationForest().setNumEstimators(100).setMaxSamples(256).setFeaturesCol("features")
           .setPredictionCol("if_label").setScoreCol("outlier_score").setContamination(0.02).setRandomSeed(1))
model = Pipeline(stages=[VectorAssembler(inputCols=["log_amount", "vendor_ratio"], outputCol="features"),
                         iforest]).fit(features)
scored = model.transform(features).select("record_key", "outlier_score").toPandas()
scored["is_outlier"] = scored["record_key"].isin(a01)
lake.write("silver_invoice_anomaly", scored)
lake.write("ref_fx_rate", pd.DataFrame({"currency": list(config.FX_TO_USD), "usd_rate": list(config.FX_TO_USD.values())}))
print(f"A01 outliers gating Gold: {len(a01):,}; isolation-forest scores written for {len(scored):,} invoices")

# %% Materialized lake views with data-quality constraints
from goldenrecord.fabric_sql import all_statements
from goldenrecord.library import RuleLibrary

enforced_custom = [r for r in RuleLibrary(lake).dq_rules() if r.get("mode") == "enforce"]
statements = all_statements(schema="dbo", custom=enforced_custom)
for name in ("silver_invoice_valid", "silver_invoice_quarantine", "silver_vendor_dq", "gold_dq_source_score"):
    spark.sql(statements[name])
    print("created/refreshed", name)
display(spark.table("gold_dq_source_score"))
