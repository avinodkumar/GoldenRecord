# Fabric deployment

The notebooks in `notebooks/` are plain Python files with `# %%` cell markers. Import each one into the
workspace as a notebook, then attach it to the Lakehouse and the Environment below.

> These notebooks have **not been run in Fabric yet**. The shared logic they call (`goldenrecord` package)
> is tested locally; the Fabric-specific parts (Spark I/O, AI Functions, MLflow) are verified on Day 1–4.

## Workspace items

| Item | Name | Purpose |
|---|---|---|
| Workspace | `ws-goldenrecord-dev` | All items below; F2+ capacity (AI Functions need paid capacity) |
| Lakehouse | `lh_goldenrecord` | Bronze, Silver and Gold Delta tables; `Files/landing`, `Files/config` |
| Environment | `env_goldenrecord` | Custom library: the `goldenrecord` wheel; `rapidfuzz`, `pyyaml` from PyPI |
| Pipeline | `pl_goldenrecord_daily` | Copy extracts → nb_01 → nb_02 → nb_03 → nb_04 |
| Notebooks | `nb_01` … `nb_05` | See table below |
| Semantic model | `sm_goldenrecord_spend` | Direct Lake on Gold only; certified (see `../powerbi/README.md`) |
| Reports | `rpt_executive_spend`, `rpt_steward_review` | Spend report; review queue with write-back |
| Activator | `act_goldenrecord_dq` | Alerts on `dq_run_metrics` (see `../activator/README.md`) |

## Notebooks

| Notebook | Layer | Reads | Writes |
|---|---|---|---|
| `nb_01_bronze_ingest` | Bronze | `Files/landing/<ERP>/*.csv` | `bronze_<erp>_vendors`, `bronze_<erp>_invoices` |
| `nb_02_silver_standardize` | Silver | Bronze tables | `silver_vendor`, `silver_invoice`, `silver_dq_failures`, `dq_scorecard`, `dq_run_metrics` |
| `nb_03_ai_match` | Silver | `silver_vendor` | `silver_match_pairs` (decision, band, explanation) |
| `nb_04_gold_golden_record` | Gold | Silver tables, `steward_decisions` | `gold_vendor`, `gold_vendor_xref`, `gold_spend_fact`, `review_queue`, `quarantine_invoice` |
| `nb_05_train_matcher_mlflow` | ML | `silver_match_pairs`, `steward_decisions` | MLflow experiment and registered model `goldenrecord-matcher` |

## Setup steps

1. Build the wheel locally: `python -m pip wheel . --no-deps -w dist`
2. In `env_goldenrecord`, upload `dist/goldenrecord-0.1.0-py3-none-any.whl` as a custom library, add
   `rapidfuzz` and `pyyaml` as public libraries, and publish the Environment.
3. Upload `config/dq_rules.yaml` to `lh_goldenrecord` → `Files/config/`.
4. Upload the generated extracts (`data/raw/ERP_*/`) to `Files/landing/` (later: Copy activities in the pipeline).
5. Run `nb_01` → `nb_04` in order, then build the pipeline that chains them.
