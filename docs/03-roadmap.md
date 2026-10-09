# 03 · Roadmap (2 weeks)

Day ranges assume 14 calendar days. Start date: **[Day 1 date]**. Roles: **PO** product owner / quality
architect (Vinod), **DE** data engineer, **AI** AI/ML engineer, **BI** Power BI developer, **QA** QA and test data.

## Milestones

| Milestone | Day | Exit criteria |
|---|---|---|
| M0 Tested core | 1 | ✅ Agents, rule library, pattern queue, PII protection, MLV SQL generation; 24 tests; ablation runs |
| M1 Fabric foundation | 3 | Workspace, Lakehouse, Environment with wheel, Key Vault key; nb_01 Bronze with tokenized PII |
| M2 Detect and learn in Fabric | 7 | nb_02 learns mappings with AI Functions (second run: 0 AI calls); nb_03 MLVs with constraints and quarantine view |
| M3 Resolve and steward | 11 | nb_04 golden records and patterns; translytical task flow approves a pattern end to end; Activator alert fires |
| M4 Demo-ready | 14 | Certified model, steward and spend reports, ablation slide from a Fabric run, rehearsed demo, backup video |

## Sprint 1 · Foundation (Days 1–3)

| ID | Story | Owner | Status |
|---|---|---|---|
| S1-01 | Synthetic multi-ERP data with seeded defects and ground truth | PO/QA | ✅ Done |
| S1-02 | Agents: Profiler, Quality, Matcher, Gatekeeper, Steward, Sentinel; rule library; pattern queue | PO/AI | ✅ Done |
| S1-03 | PII tokenization at ingestion; MLV constraint generation with parity test; ablation | PO/QA | ✅ Done |
| S1-04 | Workspace on F2+; AI Functions tenant switch confirmed; Git integration | DE | To do |
| S1-05 | Lakehouse, Environment (wheel), Key Vault secret, OneLake security roles | DE | To do |
| S1-06 | nb_01 in Fabric; Bronze counts match local; no raw PII outside `pii_vault` | DE/QA | To do |

## Sprint 2 · Detect and learn (Days 4–7)

| ID | Story | Owner |
|---|---|---|
| S2-01 | nb_02 with `FabricAIFunctionsLLM`: record AI calls on run 1 and 0 on run 2 | AI |
| S2-02 | nb_03 MLVs: `silver_invoice_valid`, quarantine view, vendor DQ, per-source score; lineage screenshot | DE |
| S2-03 | Measure AI Functions accuracy on grey-zone pairs and mappings against ground truth (fills ablation column D) | AI |
| S2-04 | SynapseML Isolation Forest scores; compare with the A01 rule | AI |
| S2-05 | Harder synthetic cases (acronyms, transliterations, missing tax IDs) | QA |

## Sprint 3 · Resolve and steward (Days 8–11)

| ID | Story | Owner |
|---|---|---|
| S3-01 | nb_04 in Fabric: golden records, merge edges, suspect-merge checks, patterns | DE/AI |
| S3-02 | Fabric SQL database inbox + User Data Functions; nb_05 applies decisions to the library | DE |
| S3-03 | `rpt_steward`: pattern queue, golden records, rule studio with data function buttons | BI |
| S3-04 | Activator: per-source score drop, suspect merges; bad batch demo trigger | AI |
| S3-05 | Pipeline `pl_goldenrecord_daily` scheduled; nb_06 MLflow model registered | DE/AI |
| S3-06 | Optional: Purview labels, lineage and DQ scorecard if the tenant has Purview | PO |

## Sprint 4 · Report and demo (Days 12–14)

| ID | Story | Owner |
|---|---|---|
| S4-01 | Certified semantic model on `gold_spend_certified`; spend and trust reports | BI |
| S4-02 | Rerun the ablation on the Fabric output; update the deck numbers | PO |
| S4-03 | Rehearse the three break-it scenarios live ([09](09-break-it-answers.md)) | All |
| S4-04 | Demo rehearsal ×2; backup video from the dev harness | All |

Feature freeze at the start of Day 12.

## Risks

| Risk | Mitigation |
|---|---|
| AI Functions tenant switch or capacity not available | Request Day 1. Agents fall back to rules; the dev harness can demo on Azure OpenAI |
| MLV feature differences from the docs (e.g. CHECK expression support) | Parity test pins the SQL; fall back to a notebook-written `silver_invoice_valid` with the same rules |
| Translytical task flows not enabled | Inbox tables can be written by a Power Apps visual; nb_05 is unchanged |
| Purview not available | Not a dependency (ADR 0005) |
| Synthetic data too easy | S2-05 harder cases; report AI-only gains separately |
