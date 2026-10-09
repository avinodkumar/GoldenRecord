# 07 · Demo script (5 minutes)

| Time | Moment | Show | Say |
|---|---|---|---|
| 0:00 | Fabric finds it | MLV lineage view: rows dropped per constraint | "Native Fabric detects: 12,164 bad invoices dropped. But no reasons, no fixes." |
| 1:00 | We explain it | `rpt_steward` pattern queue: 14,006 issues in 61 patterns | "Same rows, quarantined with reasons, grouped by root cause." |
| 2:00 | One click | Approve "ERP_B blank currency, 320 invoices"; rerun; `fixed_by` lineage | "One decision, 320 records, and every future one. Versioned." |
| 3:00 | Break it | A judge types a bad rule: blocked at 5%; unmerge a flagged false merge | "AI proposes once, rules decide, and everything is reversible." |
| 4:00 | Money | Certified spend; Activator alert from the staged bad batch | "99.1% of Gold spend on the right vendor. Zero AI calls on the rerun." |

## Preparation checklist

- [ ] Pipeline pre-run; bad batch staged in `Files/landing_demo/`
- [ ] A suspect golden record prepared for the unmerge moment
- [ ] Ablation numbers on the Measured slide refreshed from the latest run
- [ ] Teams channel open for the Activator alert
- [ ] Backup: dev harness running the same agents (`docker compose up`)
