# 03 · Roadmap (2 weeks)

Day ranges assume 14 calendar days. Start date: **[Day 1 date]**. Owners use the roles in
[06-team.md](06-team.md): **PO** product owner / quality architect (Vinod), **DE** data engineer,
**AI** AI/ML engineer, **BI** Power BI developer, **QA** QA and test data.

## Milestones

| Milestone | Day | Exit criteria |
|---|---|---|
| M0 Local core running | 1 | ✅ Done: synthetic data, local pipeline and tests pass (`python -m goldenrecord all`) |
| M0b Local stack + agents | 1 | ✅ Done: `docker compose up` runs 6 agents, UI, MLflow; deploy toolbox builds wheel + notebooks |
| M1 Fabric foundation | 3 | Workspace, Lakehouse, Environment with wheel; Bronze tables loaded |
| M2 Harmonized Gold | 7 | Silver, AI match, Gold golden record with master keys, in Fabric |
| M3 Governed | 11 | 5+ Purview rules active, Activator alert fires, labels + DLP applied, review write-back works |
| M4 Demo-ready | 14 | Certified model + spend report, DSPM screenshots, rehearsed demo, backup video |

## Sprint 1 · Foundation (Days 1–3)

| ID | Story | Owner | Status |
|---|---|---|---|
| S1-01 | Synthetic multi-ERP generator with seeded defects and ground truth | PO/QA | ✅ Done |
| S1-02 | Local pipeline: standardize, rules, matching, survivorship, metrics | PO/AI | ✅ Done |
| S1-03 | Unit and smoke tests | QA | ✅ Done |
| S1-09 | Docker stack, six agents, control-room UI, MLflow, deploy toolbox | PO/AI | ✅ Done |
| S1-10 | Run one real LLM provider end to end; record `llm_calls`, cost and guardrail overrides | AI | To do |
| S1-04 | Fabric workspace `ws-goldenrecord-dev` on F2+ capacity; confirm Copilot/Azure OpenAI tenant switch | DE | To do |
| S1-05 | Lakehouse `lh_goldenrecord`; upload extracts and `dq_rules.yaml` | DE | To do |
| S1-06 | Environment `env_goldenrecord` with the wheel; import notebooks | DE | To do |
| S1-07 | Run `nb_01`; Bronze tables verified against local counts | DE | To do |
| S1-08 | Git integration: connect workspace to the team repo | DE | To do |

## Sprint 2 · Harmonize (Days 4–7)

| ID | Story | Owner |
|---|---|---|
| S2-01 | `nb_02` Silver standardization in Fabric; counts match local run | DE |
| S2-02 | Dataflow Gen2 variant for one source (shows low-code path in the demo) | DE |
| S2-03 | `nb_03` with AI Functions on the grey zone; record `ai.stats` token usage | AI |
| S2-04 | Tune bands on labelled sample; target match precision ≥ 0.98, recall ≥ 0.95 | AI |
| S2-05 | `nb_04` Gold golden record, xref, spend fact; master-key stability check across two runs | DE/AI |
| S2-06 | Harder synthetic cases (acronyms, missing tax IDs, transliterations) so AI adds visible value | QA |

## Sprint 3 · Govern (Days 8–11)

| ID | Story | Owner |
|---|---|---|
| S3-01 | DSPM for AI "before" screenshot (before any labels) | PO |
| S3-02 | Purview: scan, data product, 9 rules active, scorecard published | PO |
| S3-03 | Activator `act_goldenrecord_dq` with 3 rules; demo bad batch triggers an alert | AI |
| S3-04 | Sensitivity labels on Lakehouse and model; DLP policy; DSPM "after" screenshot | PO |
| S3-05 | `rpt_steward_review` with translytical task flow write-back to `steward_decisions` | BI |
| S3-06 | `nb_05` MLflow training on steward labels; model registered | AI |
| S3-07 | Pipeline `pl_goldenrecord_daily` chaining everything; scheduled | DE |

## Sprint 4 · Report and demo (Days 12–14)

| ID | Story | Owner |
|---|---|---|
| S4-01 | Semantic model on Gold only; certified | BI |
| S4-02 | Executive spend report with before/after and trust pages | BI |
| S4-03 | Fill the deck placeholders from `data/reports/metrics.json` and Fabric runs | PO |
| S4-04 | Evidence pack: screenshots for each of the six deliverables | QA |
| S4-05 | Rehearse the 5-minute demo twice; record a backup video | All |

Feature freeze at the start of Day 12.

## Definition of done

- Code: tests pass locally; notebook runs cleanly in Fabric end to end.
- Data: row counts reconcile Bronze → Silver → Gold (Gold + quarantine = Silver invoices).
- Evidence: a screenshot or table that maps to one of the six deliverables.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Fabric capacity or AI Functions tenant switch not enabled | Blocks deliverable 2 | Request on Day 1; local fuzzy matcher is the fallback |
| Translytical task flows not available in tenant | Blocks write-back | Power Apps visual fallback |
| Purview DQ needs admin rights we lack | Blocks deliverable 4 | Identify Purview admin on Day 1; local rules as evidence meanwhile |
| Synthetic data too easy (local matcher already near-perfect) | AI looks unnecessary | S2-06 harder cases |
| AI Function cost/throughput | Slow runs | Only grey-zone pairs go to AI; monitor `ai.stats` |
