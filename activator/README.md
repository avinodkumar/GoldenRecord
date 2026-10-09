# Fabric Activator: alert when a source's quality drops

| Activator rule | Source | Object | Condition | Action |
|---|---|---|---|---|
| Source quality dropped | Trust page visual on `dq_source_score_history` (or an Eventstream) | `source_system` | `dq_score` decreases by more than 0.02 from the previous value | Teams message to that source's data owner |
| Suspect golden records | `gold_cluster_alerts` row count | workspace | increases | Teams message to the steward channel |
| Anomaly spike | `dq_run_metrics.anomalies` | run | increases by more than 50 | Email to the finance data owner |
| Rule breach | `dq_run_metrics.worst_rule_pass_rate` | run | below 0.75 | Teams message naming `worst_rule` |

The Sentinel agent (`nb_04`) writes these tables and the explanation text. Activator does the alerting and
routing. The same rules live in `config/alert_rules.yaml` (AL01–AL06), so the dev harness alerts identically.

**Demo trigger:** copy the prepared bad batch (3,000 broken ERP_A invoices) into `Files/landing/ERP_A/`,
run the pipeline, and show the "ERP_A quality dropped" Teams message.
