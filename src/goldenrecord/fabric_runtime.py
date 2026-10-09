"""Adapters that run the GoldenRecord agents inside Microsoft Fabric, unchanged.

  FabricLakehouse        same interface as store.Lakehouse, backed by Spark Delta tables in the attached
                         Lakehouse (OneLake) and the mounted Files area for landing extracts.
  FabricAIFunctionsLLM   same interface as llm.LLMClient, backed by Fabric AI Functions
                         (ai.generate_response with a JSON schema). No keys, no external endpoint:
                         calls run on the built-in Fabric model and bill to the capacity.

Import only inside a Fabric notebook (needs `spark` and the AI Functions library).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .llm import LLMClient
from .store import _to_arrow


class FabricLakehouse:
    def __init__(self, spark, files_root: str = "/lakehouse/default/Files"):
        self.spark = spark
        self.files_dir = Path(files_root)

    @property
    def landing_dir(self) -> Path:
        return self.files_dir / "landing"

    @property
    def truth_dir(self) -> Path:
        return self.files_dir / "truth"

    def exists(self, name: str) -> bool:
        return self.spark.catalog.tableExists(name)

    def read(self, name: str, columns: list[str] | None = None) -> pd.DataFrame:
        if not self.exists(name):
            return pd.DataFrame(columns=columns or [])
        sdf = self.spark.table(name)
        df = (sdf.select(*columns) if columns else sdf).toPandas()
        for col in df.columns:
            if not pd.api.types.is_numeric_dtype(df[col]) and not pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = df[col].astype(object).where(df[col].notna(), None)
        return df

    def write(self, name: str, df: pd.DataFrame, mode: str = "overwrite") -> None:
        from pyspark.sql import functions as F
        from pyspark.sql.types import NullType

        sdf = self.spark.createDataFrame(_to_arrow(df).to_pandas())
        for field in sdf.schema.fields:  # Delta cannot store an all-null (NullType) column
            if isinstance(field.dataType, NullType):
                sdf = sdf.withColumn(field.name, F.col(field.name).cast("string"))
        writer = sdf.write.format("delta").mode(mode)
        writer = writer.option("overwriteSchema", "true") if mode == "overwrite" else writer.option("mergeSchema", "true")
        writer.saveAsTable(name)

    def append(self, name: str, df: pd.DataFrame) -> None:
        self.write(name, df, mode="append")

    def tables(self) -> list[str]:
        return sorted(t.name for t in self.spark.catalog.listTables())


class FabricAIFunctionsLLM(LLMClient):
    """The agents' LLM interface on Fabric AI Functions. One call = one ai.generate_response row."""
    provider = "fabric_ai_functions"
    model = "fabric-default"

    def __init__(self):
        super().__init__()
        import synapse.ml.aifunc as aifunc  # noqa: F401  registers the pandas .ai accessor

    def _complete_json(self, system: str, prompt: str, schema: dict) -> dict | None:
        df = pd.DataFrame({"request": [f"{system}\n\n{prompt}"]})
        out = df.ai.generate_response(
            "{request}", is_prompt_template=True,
            response_format={"type": "json_schema",
                             "json_schema": {"name": "result", "strict": True, "schema": schema}},
        )
        value = out.iloc[0]
        if value is None or not isinstance(value, (str, dict)):
            return None  # aifunc.ExceptionResult / FilterResult: fall back to rules
        return value if isinstance(value, dict) else json.loads(value)
