# 07 · Demo script (5 minutes)

| Time | Moment | Show | Say |
|---|---|---|---|
| 0:00 | Ingest | Pipeline run; three Bronze tables | "Three ERPs, 52,000 records, each in its own format." |
| 1:00 | Match | `silver_match_pairs` filtered to AI-reviewed pairs | "Every pair gets a decision, a confidence band and a reason." |
| 2:00 | Review | `rpt_steward_review`: approve one MEDIUM pair | "Uncertain cases go to a person, and each decision becomes a training label." |
| 3:00 | Alert | Drop the bad batch; Activator message in Teams | "A broken batch is caught before anyone reads a report." |
| 4:00 | Report | Executive spend report, before/after page | "Same spend, now attributed to the real vendors, from certified Gold data only." |

## Preparation checklist

- [ ] Pipeline pre-run so Gold is populated; bad batch staged in `Files/landing_demo/`
- [ ] One MEDIUM pair chosen in advance with a clear explanation
- [ ] Teams channel open on a second screen
- [ ] Deliverables slide numbers filled from the latest run
- [ ] Backup video recorded (Day 14)
