# Fabric Activator: anomaly and rule-breach alerts

Deliverable 4 (second half). `nb_02_silver_standardize` appends one row per run to the Delta table
`dq_run_metrics`:

| Column | Meaning |
|---|---|
| `run_at` | Run timestamp (UTC) |
| `records` | Records evaluated |
| `pass_rate` | Share of records passing every rule |
| `anomalies` | Invoices flagged by A01 (amount > 20× the vendor median) |
| `worst_rule`, `worst_rule_pass_rate` | The weakest rule this run |

## Activator item `act_goldenrecord_dq`

1. Source: `lh_goldenrecord.dq_run_metrics` (or an Eventstream fed by the pipeline, if near-real-time is needed).
2. Object: **DQ run**, keyed on `run_at`.
3. Rules:

| Rule | Condition | Action |
|---|---|---|
| Pass rate drop | `pass_rate` < 0.80 | Teams message to the data-steward channel |
| Anomaly spike | `anomalies` > 100 | Email to the finance data owner |
| Rule breach | `worst_rule_pass_rate` < 0.70 | Teams message naming `worst_rule` |

Thresholds are starting values; tune them on Day 10 against the synthetic baseline.

## Demo trigger

Keep a prepared "bad batch" extract (for example, 500 invoices with negative amounts) in
`Files/landing_demo/`. During the demo, copy it into `Files/landing/`, run the pipeline and show the
Teams alert arriving.
