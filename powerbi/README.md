# Power BI: certified model, spend report and review queue

Deliverables 3 and 6.

## Semantic model `sm_goldenrecord_spend` (Direct Lake, Gold only)

| Table | Source | Notes |
|---|---|---|
| `Vendor` | `gold_vendor` | Hide `bank_account`; key `master_key` |
| `Spend` | `gold_spend_fact` | Fact; `master_key` → `Vendor`, `invoice_date` → `Date` |
| `Date` | Generated date table | Mark as date table |
| `DQ Scorecard` | `dq_scorecard` | Disconnected; for the trust page |

Measures:

```DAX
Total Spend USD = SUM ( Spend[amount_usd] )
Invoice Count = COUNTROWS ( Spend )
Active Vendors = DISTINCTCOUNT ( Spend[master_key] )
Avg Invoice USD = DIVIDE ( [Total Spend USD], [Invoice Count] )
Multi-ERP Vendors = CALCULATE ( COUNTROWS ( Vendor ), Vendor[member_count] > 1 )
DQ Pass Rate = AVERAGE ( 'DQ Scorecard'[pass_rate] )
```

Certification: the workspace admin endorses the model as **Certified** (requires the tenant
endorsement setting). The model must not reference any Bronze or Silver table.

## Report `rpt_executive_spend`

1. **Executive spend**: total spend, top 10 vendors, spend by country and month, multi-ERP vendors.
2. **Before and after**: spend by vendor when the three ERPs are added up separately versus harmonized
   (duplicate vendors merged, quarantined invoices excluded).
3. **Trust**: DQ pass rate by rule, quarantined invoice count, link to the Purview scorecard.

## Report `rpt_steward_review` (write-back)

Source: `review_queue` (pairs in the MEDIUM band with their explanation).

Write-back uses a **translytical task flow**: a button calls a Fabric User Data Function that inserts
`{left_key, right_key, decision, reviewer, decided_at}` into the `steward_decisions` table.
`nb_04` merges approved pairs on the next run; `nb_05` trains on the labels.

Fallback if task flows are unavailable in the tenant: a Power Apps visual writing to the same table.
During local development, `python -m goldenrecord review` simulates the steward from ground truth.
