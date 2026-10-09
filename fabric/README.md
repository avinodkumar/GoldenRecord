# Fabric deployment

> Not yet run in a Fabric workspace. The package the notebooks call is covered by tests locally; the
> Fabric-specific parts (Spark I/O, AI Functions, MLVs, SynapseML, User Data Functions) are verified in
> Sprint 1–2 (roadmap S1-04 onwards).

## Items

| Item | Name | Purpose |
|---|---|---|
| Workspace | `ws-goldenrecord-dev` | F2+ capacity (AI Functions need paid capacity and the Copilot/Azure OpenAI tenant switch) |
| Lakehouse | `lh_goldenrecord` (schemas enabled, `dbo`) | Bronze, Silver, Gold, control tables; `Files/landing` |
| Environment | `env_goldenrecord` | The `goldenrecord` wheel (custom library), `rapidfuzz`, `pyyaml`, `deltalake`, `pyarrow` |
| Key Vault secret | `goldenrecord-pii-token-key` | HMAC key for PII tokens (read by nb_01) |
| Pipeline | `pl_goldenrecord_daily` | Copy → nb_05 → nb_01 → nb_02 → nb_03 → nb_04 |
| SQL database | `sqldb_goldenrecord_steward` | Steward inbox (`sql/steward_inbox.sql`); shortcut its tables into the Lakehouse |
| User Data Functions | `udf_goldenrecord_steward` | `functions/function_app.py`: decide_pattern, unmerge_record, request_rule |
| Semantic model | `sm_goldenrecord_spend` | Direct Lake on `gold_spend_certified` + `gold_vendor`; certified |
| Reports | `rpt_executive_spend`, `rpt_steward` | Spend and trust; pattern queue with data function buttons |
| Activator | `act_goldenrecord_dq` | Rules on `dq_source_score_history`, `gold_cluster_alerts`, `dq_run_metrics` |

## Notebooks

| Notebook | Does | Native Fabric features |
|---|---|---|
| `nb_01_ingest_bronze` | Landing → Bronze with PII tokenized and masked; raw PII → `pii_vault` | Key Vault via `notebookutils`, OneLake security |
| `nb_02_learn_and_silver` | Profiler learns mappings for distinct unknown values; Silver built by lookup | **AI Functions** (`ai.generate_response`, JSON schema) |
| `nb_03_detect_native` | Outlier scores; MLV constraints, quarantine with reasons, vendor DQ, per-source score | **Materialized lake views**, **SynapseML Isolation Forest** |
| `nb_04_resolve_and_remediate` | Quality, Matcher, Gatekeeper, Steward patterns, Sentinel; certified spend view | AI Functions (grey zone only), MLV |
| `nb_05_apply_steward_inbox` | Applies Power BI steward actions to the rule library (versioned) | SQL database replicated to OneLake |
| `nb_06_train_matcher_mlflow` | Trains the match classifier on steward labels | Fabric Data Science MLflow |

## Setup

1. `docker compose --profile deploy run --rm toolbox` (or `python -m build --wheel`) → `dist/goldenrecord-*.whl`.
2. Upload the wheel to `env_goldenrecord`, add the PyPI libraries above, publish, attach to all notebooks.
3. Upload `config/` to `Files/config/`; set `GOLDENRECORD_CONFIG_DIR=/lakehouse/default/Files/config` in the Environment.
4. Create the SQL database tables (`sql/steward_inbox.sql`), the UDF item, and the Lakehouse shortcuts.
5. Configure OneLake security roles (`sql/onelake_security.md`).
6. Run nb_01 → nb_04 once by hand, then build the pipeline and the Power BI reports (`../powerbi/README.md`).
