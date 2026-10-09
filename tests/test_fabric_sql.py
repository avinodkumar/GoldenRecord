"""The materialized-lake-view constraints generated for Fabric must fail exactly the records the
Python rules engine fails. Checked by running the generated CHECK expressions in DuckDB."""
import re
from datetime import date

import duckdb
import pandas as pd
import pytest

from goldenrecord import synth
from goldenrecord.agents.orchestrator import run_pipeline
from goldenrecord.fabric_sql import all_statements, check_expression, invoice_checks
from goldenrecord.rules import detect_amount_anomalies, load_rules, run_rules
from goldenrecord.store import Lakehouse

AS_OF = date(2026, 10, 9)


def to_duckdb(expr: str) -> str:
    """Translate the few Spark SQL constructs used in checks into DuckDB SQL."""
    expr = expr.replace("current_date()", f"DATE '{AS_OF.isoformat()}'")
    expr = re.sub(r"(\w+) RLIKE '((?:[^'\\]|\\.)*)'",
                  lambda m: f"regexp_matches({m.group(1)}, '{m.group(2).replace(chr(92) * 2, chr(92))}')", expr)
    return expr


@pytest.fixture(scope="module")
def silver(tmp_path_factory):
    lake = Lakehouse(tmp_path_factory.mktemp("sql") / "lakehouse")
    synth.generate(n_vendors=250, n_invoices=3000, seed=9, raw_dir=lake.landing_dir, truth_dir=lake.truth_dir)
    run_pipeline(lake, as_of=AS_OF, use_env_llm=False)
    return lake.read("silver_vendor"), lake.read("silver_invoice")


def test_generated_constraints_match_the_python_rules(silver):
    vendors, invoices = silver
    rules = load_rules()
    failures, _ = run_rules(vendors, invoices, rules, AS_OF)
    expected = failures.groupby("rule_id")["record_key"].agg(set).to_dict()
    anomalies = detect_amount_anomalies(invoices)

    con = duckdb.connect()
    con.register("silver_vendor", vendors)
    con.register("silver_invoice", invoices.assign(invoice_date=pd.to_datetime(invoices["invoice_date"]).dt.date))
    con.register("anomaly", anomalies.assign(is_outlier=True))
    con.execute("""CREATE TABLE inv AS SELECT i.*, v.record_key IS NOT NULL AS vendor_exists,
                   COUNT(*) OVER (PARTITION BY i.record_key) AS dup_count,
                   COALESCE(a.is_outlier, FALSE) AS is_outlier
                   FROM silver_invoice i
                   LEFT JOIN (SELECT DISTINCT record_key FROM silver_vendor) v ON i.vendor_record_key = v.record_key
                   LEFT JOIN anomaly a ON i.record_key = a.record_key""")
    for rule in rules:
        table = "silver_vendor" if rule["entity"] == "vendor" else "inv"
        sql = f"SELECT DISTINCT record_key FROM {table} WHERE NOT coalesce({to_duckdb(check_expression(rule))}, FALSE)"
        got = set(con.execute(sql).df()["record_key"])
        assert got == expected.get(rule["id"], set()), rule["id"]
    a01 = set(con.execute("SELECT DISTINCT record_key FROM inv WHERE is_outlier").df()["record_key"])
    assert a01 == set(anomalies["record_key"])


def test_statements_cover_every_invoice_rule_and_escape_regexes():
    statements = all_statements()
    valid, quarantine = statements["silver_invoice_valid"], statements["silver_invoice_quarantine"]
    for rule_id, _, _ in invoice_checks():
        assert f"CONSTRAINT {rule_id}_" in valid and f"'{rule_id}'" in quarantine
    assert valid.count("ON MISMATCH DROP") == len(invoice_checks())
    assert "\\\\s" in statements["silver_vendor_dq"]  # Spark unescapes literals, so \s is written \\s
    custom = [{"id": "C01", "name": "Amount cap", "entity": "invoice", "type": "range", "column": "amount",
               "max": 1e6, "mode": "enforce"}]
    assert "CONSTRAINT C01_amount_cap" in all_statements(custom=custom)["silver_invoice_valid"]
