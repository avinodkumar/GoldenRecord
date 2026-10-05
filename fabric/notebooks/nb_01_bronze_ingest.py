# Fabric notebook: nb_01_bronze_ingest  (PySpark)
# Called by pipeline pl_goldenrecord_daily after the Copy activities land ERP extracts in
# Files/landing/<ERP>/<entity>.csv of lh_goldenrecord. Writes one Bronze Delta table per extract.

# %% Parameters
landing_root = "Files/landing"
sources = ["ERP_A", "ERP_B", "ERP_C"]
entities = ["vendors", "invoices"]

# %% Ingest as-is: every column stays a string; lineage columns are added
from pyspark.sql import functions as F

run_ts = F.current_timestamp()
for source in sources:
    for entity in entities:
        path = f"{landing_root}/{source}/{entity}.csv"
        df = (spark.read.option("header", True).option("inferSchema", False).csv(path)
              .withColumn("_source_system", F.lit(source))
              .withColumn("_source_file", F.input_file_name())
              .withColumn("_ingested_at", run_ts))
        table = f"bronze_{source.lower()}_{entity}"
        df.write.mode("overwrite").format("delta").saveAsTable(table)
        print(f"{table}: {df.count()} rows")
