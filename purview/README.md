# Microsoft Purview: data quality and protection

Deliverables 4 and 5. The rule catalog lives in [`config/dq_rules.yaml`](../config/dq_rules.yaml); the
same rules run locally in `goldenrecord.rules`, so we can test them before configuring Purview.

## 1. Catalog setup

1. Register the Fabric tenant as a data source in the Purview Unified Catalog and scan `ws-goldenrecord-dev`.
2. Create governance domain **Procurement** and data product **Vendor Master & Spend**.
3. Add the Silver and Gold tables as data assets of that product: `silver_vendor`, `silver_invoice`,
   `gold_vendor`, `gold_vendor_xref`, `gold_spend_fact`.
4. Add reference tables `ref_country` and `ref_currency` (used by lookup rules R03 and R07).

## 2. Data-quality rules (brief: at least five active)

| ID | Rule | Table.column | Purview rule type | Dimension |
|---|---|---|---|---|
| R01 | Vendor tax ID is present | silver_vendor.tax_id | Empty/blank fields | Completeness |
| R02 | Tax ID matches `^[A-Z]{2}[A-Z0-9]{10}$` | silver_vendor.tax_id | String format match | Validity |
| R03 | Country is a valid ISO code | silver_vendor.country_iso2 | Table lookup | Validity |
| R04 | Email has a valid format | silver_vendor.email | String format match | Validity |
| R05 | Amount present and > 0 | silver_invoice.amount | Custom expression | Validity |
| R06 | Invoice date valid and not future | silver_invoice.invoice_date | Custom expression | Timeliness |
| R07 | Currency supported | silver_invoice.currency | Table lookup | Validity |
| R08 | Vendor exists in master | silver_invoice.vendor_record_key | Table lookup | Consistency |
| R09 | Invoice unique per source | silver_invoice.record_key | Unique values | Uniqueness |

Rule-type names can differ slightly in the Purview UI; map each rule to the closest built-in type and
fall back to a custom expression. **Evidence for judges:** screenshot of the rules list (all active), a
completed scan run, and the published data-quality scorecard for the data product.

## 3. Protection

| Control | Where | Setting |
|---|---|---|
| Sensitivity label **Confidential – Vendor Financial** | `lh_goldenrecord`, `sm_goldenrecord_spend`, `rpt_executive_spend` | Apply in Fabric item settings; enable label inheritance downstream |
| Sensitivity label **Highly Confidential – Bank Details** | Column `bank_account` in Silver/Gold | Classification via Purview scan; excluded from the semantic model |
| DLP policy | Fabric / Power BI semantic models | Detect bank-account and tax-ID patterns; policy tip + alert on export |
| DSPM for AI | Purview portal → DSPM for AI | Run the data-risk assessment before and after labels/DLP; **screenshot both** |

The DSPM for AI assessment screenshot must show reduced exposure after the controls are applied
(deliverable 5). Take the "before" screenshot on Day 8, before any labels are applied.
