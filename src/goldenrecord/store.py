"""Local lakehouse: Delta tables under Tables/, raw files under Files/ (a stand-in for a Fabric Lakehouse).

Tables are real Delta Lake tables (delta-rs), so they can be inspected with any Delta reader and
queried with DuckDB as a SQL-endpoint stand-in.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
from deltalake import DeltaTable, write_deltalake

from .config import LAKEHOUSE_ROOT


def _to_arrow(df: pd.DataFrame) -> pa.Table:
    """Make a pandas frame Delta-friendly: no all-null columns, microsecond timestamps."""
    out = df.copy()
    for col in out.columns:
        series = out[col]
        if pd.api.types.is_datetime64_any_dtype(series):
            out[col] = series.dt.tz_localize("UTC") if series.dt.tz is None else series
            out[col] = out[col].astype("datetime64[us, UTC]")
        elif series.dtype == object:
            non_null = series.dropna()
            if non_null.empty:
                out[col] = series.astype("string")
            elif len({type(v) for v in non_null}) > 1:
                out[col] = series.map(lambda v: None if v is None or (isinstance(v, float) and pd.isna(v)) else str(v))
    return pa.Table.from_pandas(out, preserve_index=False)


class Lakehouse:
    def __init__(self, root: Path | str = LAKEHOUSE_ROOT):
        self.root = Path(root)
        self.tables_dir = self.root / "Tables"
        self.files_dir = self.root / "Files"
        self.tables_dir.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(parents=True, exist_ok=True)

    @property
    def landing_dir(self) -> Path:
        return self.files_dir / "landing"

    @property
    def truth_dir(self) -> Path:
        return self.files_dir / "truth"

    def _path(self, name: str) -> Path:
        return self.tables_dir / name

    def exists(self, name: str) -> bool:
        return (self._path(name) / "_delta_log").exists()

    def write(self, name: str, df: pd.DataFrame, mode: str = "overwrite") -> None:
        schema_mode = "overwrite" if mode == "overwrite" else "merge"
        write_deltalake(str(self._path(name)), _to_arrow(df), mode=mode, schema_mode=schema_mode)

    def append(self, name: str, df: pd.DataFrame) -> None:
        self.write(name, df, mode="append")

    def read(self, name: str, columns: list[str] | None = None) -> pd.DataFrame:
        if not self.exists(name):
            return pd.DataFrame(columns=columns or [])
        df = DeltaTable(str(self._path(name))).to_pandas(columns=columns)
        # Text columns: the business logic expects None for nulls. Numeric columns keep NaN.
        for col in df.columns:
            if not pd.api.types.is_numeric_dtype(df[col]) and not pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = df[col].astype(object).where(df[col].notna(), None)
        return df

    def tables(self) -> list[str]:
        return sorted(p.name for p in self.tables_dir.iterdir() if (p / "_delta_log").exists())

    def sql(self, query: str, tables: list[str]) -> pd.DataFrame:
        """Run DuckDB SQL over the named Delta tables (SQL analytics endpoint stand-in)."""
        import duckdb

        con = duckdb.connect()
        for name in tables:
            con.register(name, self.read(name))
        return con.execute(query).df()
