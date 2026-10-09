# Power BI: certified spend, trust, and the steward workspace

## Semantic model `sm_goldenrecord_spend` (Direct Lake, Gold only, certified)

| Table | Source | Notes |
|---|---|---|
| `Spend` | MLV `gold_spend_certified` | Valid invoices on golden vendors; `master_key` → `Vendor` |
| `Vendor` | `gold_vendor` | Token and bank columns excluded from the model |
| `Source score` | MLV `gold_dq_source_score` + `dq_source_score_history` | Trust page; Activator trigger |
| `Date` | Generated | Marked as date table |

```DAX
Total Spend USD = SUM ( Spend[amount_usd] )
Active Vendors = DISTINCTCOUNT ( Spend[master_key] )
Multi-ERP Vendors = CALCULATE ( COUNTROWS ( Vendor ), Vendor[member_count] > 1 )
Source DQ Score = AVERAGE ( 'Source score'[dq_score] )
```

## Report `rpt_executive_spend`

1. **Spend:** total, top vendors, by country and month, all on golden vendors.
2. **Before / after:** spend split across raw ERP vendor IDs versus consolidated on golden records.
3. **Trust:** quality score per source over time (Activator alert set on this visual), quarantined
   invoices by rule, rule-library version in use.

## Report `rpt_steward` (translytical task flows)

All actions call `udf_goldenrecord_steward` (`fabric/functions/function_app.py`) through data function
buttons. Each records the steward's Entra identity and returns a confirmation string.

| Page | Data | Button → function |
|---|---|---|
| Pattern queue | `steward_patterns` sorted by affected records; canonical-value slicer for mapping patterns | **Approve for all** → `decide_pattern(patternId, "approve", canonical)`; **Reject** → `decide_pattern(…, "reject")` |
| Golden records | `gold_cluster_alerts`, `gold_merge_edges`, `gold_vendor_xref` | **Unmerge** → `unmerge_record(recordKey, note)` |
| Rule studio | Text input; `rule_previews` (impact by source, blocked flag) | **Preview** → `request_rule(text)`; **Accept in shadow** → `request_rule(text, accept=True)` |
| Rule library | `rule_library` (versioned, append-only) | Read-only; retire via the inbox (backlog) |

Decisions land in the Fabric SQL database inbox and are applied by `nb_05` at the start of the next
pipeline run (or on demand), so every approval becomes a versioned library item.
