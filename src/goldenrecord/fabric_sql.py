"""Generate the Spark SQL for Fabric materialized lake views (MLVs) from config/dq_rules.yaml.

One rule catalog drives three enforcement points, so they cannot drift apart:
  * MLV constraints (CONSTRAINT ... CHECK ... ON MISMATCH DROP) gate invoices into silver.invoice_valid
  * the quarantine MLV explains every dropped invoice with the rule IDs it failed
  * Purview data-quality rules (configured from the same IDs, see purview/README.md)

The local rules engine (rules.py) evaluates the same catalog, which is how these are tested offline.
"""
from __future__ import annotations

from .rules import load_rules

# Columns computed inside the MLV query so row-level CHECKs can express cross-row rules.
COMPUTED = {
    "reference": "vendor_exists",
    "unique": "dup_count = 1",
}
ANOMALY_CHECK = ("A01", "Invoice amount is not an outlier", "NOT is_outlier")


def _quote(v) -> str:
    """Spark SQL string literal. Spark unescapes backslashes in literals, so they are doubled."""
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def check_expression(rule: dict) -> str:
    """Spark SQL boolean that is TRUE when a row passes the rule."""
    col, kind = rule.get("column"), rule["type"]
    if kind == "not_null":
        return f"{col} IS NOT NULL"
    if kind == "regex":
        expr = f"{col} RLIKE {_quote(rule['pattern'])}"
        return f"({col} IS NULL OR {expr})" if rule.get("skip_null") else f"({col} IS NOT NULL AND {expr})"
    if kind == "positive":
        return f"({col} IS NOT NULL AND {col} > 0)"
    if kind == "range":
        parts = [f"{col} IS NOT NULL"]
        if rule.get("min") is not None:
            parts.append(f"{col} >= {float(rule['min'])}")
        if rule.get("max") is not None:
            parts.append(f"{col} <= {float(rule['max'])}")
        return "(" + " AND ".join(parts) + ")"
    if kind == "date_not_future":
        return f"({col} IS NOT NULL AND {col} <= current_date())"
    if kind == "allowed_values":
        return f"{col} IN ({', '.join(_quote(v) for v in rule['values'])})"
    if kind in COMPUTED:
        return COMPUTED[kind]
    raise ValueError(f"no Spark SQL mapping for rule type {kind!r} ({rule['id']})")


def _constraint_name(rule_id: str, name: str) -> str:
    slug = "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")
    return f"{rule_id}_{slug}"[:60]


def invoice_checks(rules: list[dict] | None = None, custom: list[dict] | None = None) -> list[tuple[str, str, str]]:
    """(rule_id, name, CHECK expression) for every invoice rule, steward-approved rules and the anomaly check."""
    rules = [r for r in (rules or load_rules()) + (custom or []) if r["entity"] == "invoice"]
    return [(r["id"], r["name"], check_expression(r)) for r in rules] + [ANOMALY_CHECK]


INVOICE_BASE = """SELECT i.*,
       v.record_key IS NOT NULL                       AS vendor_exists,
       COUNT(*) OVER (PARTITION BY i.record_key)       AS dup_count,
       COALESCE(a.is_outlier, FALSE)                   AS is_outlier,
       a.outlier_score
FROM {schema}.silver_invoice i
LEFT JOIN {schema}.silver_vendor v ON i.vendor_record_key = v.record_key
LEFT JOIN {schema}.silver_invoice_anomaly a ON i.record_key = a.record_key"""


def mlv_invoice_valid(schema: str = "dbo", rules=None, custom=None) -> str:
    """Silver invoices that pass every rule. Violations are dropped and counted in MLV lineage."""
    constraints = ",\n  ".join(
        f"CONSTRAINT {_constraint_name(rid, name)} CHECK (coalesce({expr}, FALSE)) ON MISMATCH DROP"
        for rid, name, expr in invoice_checks(rules, custom))
    return (f"CREATE OR REPLACE MATERIALIZED LAKE VIEW {schema}.silver_invoice_valid\n(\n  {constraints}\n)\n"
            f"COMMENT 'Invoices that pass every GoldenRecord data-quality rule'\nAS\n"
            + INVOICE_BASE.format(schema=schema))


def mlv_invoice_quarantine(schema: str = "dbo", rules=None, custom=None) -> str:
    """The complement of silver_invoice_valid, with the IDs of the rules each invoice failed."""
    cases = ",\n             ".join(f"CASE WHEN NOT coalesce({expr}, FALSE) THEN '{rid}' END"
                                   for rid, _, expr in invoice_checks(rules, custom))
    return (f"CREATE OR REPLACE MATERIALIZED LAKE VIEW {schema}.silver_invoice_quarantine\n"
            f"COMMENT 'Invoices held back from Gold, with the rules they failed'\nAS\n"
            f"SELECT * FROM (\n  SELECT b.*,\n         filter(array(\n             {cases}\n"
            f"         ), x -> x IS NOT NULL) AS failed_rules\n"
            f"  FROM (\n{INVOICE_BASE.format(schema=schema)}\n  ) b\n) q\nWHERE size(failed_rules) > 0")


def mlv_vendor_dq(schema: str = "dbo", rules=None) -> str:
    """One boolean pass column per vendor rule. Vendors are flagged, never dropped: matching needs them all."""
    vendor = [r for r in (rules or load_rules()) if r["entity"] == "vendor"]
    cols = ",\n       ".join(f"{check_expression(r)} AS pass_{r['id']}" for r in vendor)
    all_pass = " AND ".join(f"coalesce({check_expression(r)}, FALSE)" for r in vendor)
    return (f"CREATE OR REPLACE MATERIALIZED LAKE VIEW {schema}.silver_vendor_dq\nAS\n"
            f"SELECT record_key, source_system,\n       {cols},\n       {all_pass} AS passes_all\n"
            f"FROM {schema}.silver_vendor")


def mlv_dq_source_score(schema: str = "dbo") -> str:
    """Per-source quality score (share of records passing every rule). Activator alerts on drops."""
    return f"""CREATE OR REPLACE MATERIALIZED LAKE VIEW {schema}.gold_dq_source_score
COMMENT 'Share of records passing every rule, per ERP source (Activator watches this)'
AS
WITH records AS (
  SELECT source_system, 'vendor' AS entity, CAST(passes_all AS INT) AS passed FROM {schema}.silver_vendor_dq
  UNION ALL
  SELECT i.source_system, 'invoice', CASE WHEN q.record_key IS NULL THEN 1 ELSE 0 END
  FROM {schema}.silver_invoice i
  LEFT JOIN (SELECT DISTINCT record_key FROM {schema}.silver_invoice_quarantine) q ON i.record_key = q.record_key
)
SELECT source_system,
       COUNT(*)                         AS records,
       ROUND(AVG(passed), 4)            AS dq_score,
       SUM(CASE WHEN entity = 'invoice' AND passed = 0 THEN 1 ELSE 0 END) AS quarantined_invoices,
       current_timestamp()              AS scored_at
FROM records
GROUP BY source_system"""


def mlv_gold_spend(schema: str = "dbo") -> str:
    """Governed spend: valid invoices mapped to golden vendors. The certified semantic model reads only this."""
    return f"""CREATE OR REPLACE MATERIALIZED LAKE VIEW {schema}.gold_spend_certified
(
  CONSTRAINT G01_vendor_mastered CHECK (master_key IS NOT NULL) ON MISMATCH DROP,
  CONSTRAINT G02_fx_known CHECK (amount_usd IS NOT NULL) ON MISMATCH DROP
)
COMMENT 'Governed spend for the certified semantic model: valid invoices on golden vendors'
AS
SELECT v.record_key, x.master_key, v.source_system, v.invoice_no, v.invoice_date, v.currency, v.amount,
       ROUND(v.amount * fx.usd_rate, 2) AS amount_usd
FROM {schema}.silver_invoice_valid v
LEFT JOIN {schema}.gold_vendor_xref x ON v.vendor_record_key = x.record_key
LEFT JOIN {schema}.ref_fx_rate fx ON v.currency = fx.currency"""


def all_statements(schema: str = "dbo", custom: list[dict] | None = None) -> dict[str, str]:
    """Statements in dependency order (Silver first). Gold spend needs gold_vendor_xref from nb_04."""
    return {
        "silver_invoice_valid": mlv_invoice_valid(schema, custom=custom),
        "silver_invoice_quarantine": mlv_invoice_quarantine(schema, custom=custom),
        "silver_vendor_dq": mlv_vendor_dq(schema),
        "gold_dq_source_score": mlv_dq_source_score(schema),
        "gold_spend_certified": mlv_gold_spend(schema),
    }
