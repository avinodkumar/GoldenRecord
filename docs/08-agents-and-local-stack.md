# 08 · Agents and the local Docker stack

Fabric, Purview, Activator and Power BI are cloud services, so the Docker stack runs an open-source
stand-in for each one. The business logic is the same package the Fabric notebooks use, so results
carry over ([ADR 0004](adr/0004-local-stack-stand-ins.md)).

## Run it

```bash
cp .env.example .env            # optional: choose an LLM provider; default is rules-only
docker compose up -d --build
```

| URL | What |
|---|---|
| http://localhost:8501 | Control room UI: overview, executive spend, review queue, rule studio, data quality, alerts |
| http://localhost:8000/docs | Agent API (OpenAPI) |
| http://localhost:5000 | MLflow: experiment `goldenrecord-matcher`, registered model |

On first start the API generates the synthetic ERP extracts and runs the pipeline once (about 15 s).

## Fabric item → local stand-in

| Fabric / Microsoft | Local container | Notes |
|---|---|---|
| OneLake + Lakehouse | `lakehouse` volume: Delta tables (delta-rs) in `Tables/`, extracts in `Files/landing` | Real Delta format; DuckDB gives SQL over it |
| Data Factory pipeline + schedule | Orchestrator in `api` (`POST /runs`, `SCHEDULE_MINUTES`) | Same Bronze → Silver → Gold order as `pl_goldenrecord_daily` |
| Notebooks + AI Functions | Agents in `api`; LLM chosen by `LLM_PROVIDER` | `none` = deterministic fallbacks |
| Purview DQ rules + scorecard | Quality agent; UI "Data quality" page | Same 9 rules (`config/dq_rules.yaml`) |
| Activator | Sentinel agent; `ALERT_WEBHOOK_URL` for Teams | Rules in `config/alert_rules.yaml` |
| Power BI report + write-back | `ui` (Streamlit) via the agent API | Spend page reads Gold only |
| Fabric Data Science / MLflow | `mlflow` server + model registry | |
| Deployment | `toolbox` (profile `deploy`): tests, wheel, notebook export, `fab import` | Fabric CLI 1.7 |

## The agents

Each agent owns one step, writes what it decided and why to the `agent_events` table (the audit
trail), and falls back to deterministic rules when no LLM is configured or a call fails.

| Agent | Runs | Uses the LLM to | Without an LLM |
|---|---|---|---|
| **Profiler** | Every run; on demand in Rule studio | Summarize profile findings; turn a sentence into a rule (JSON schema) | Null-rate findings; phrase patterns ("must not be empty", "must not exceed N") |
| **Quality** | Every run | Two-sentence executive summary of the scorecard | Lists the weakest rules |
| **Matcher** | Every run | Judge grey-zone pairs (score 0.50–0.90): decision, confidence, explanation, batched 10 per call | Deterministic score and band |
| **Gatekeeper** | Every run | Never: it is the guardrail | Applies `guarded_band`, steward decisions, survivorship, quarantine |
| **Steward assistant** | On demand from the review queue | Brief the steward and recommend a decision | Recommendation from the score and tax-ID evidence |
| **Sentinel** | Every run | Write the likely cause and next step for each alert | Names the rules whose failures grew most |

**Guardrails on the LLM**

- A pair reaches HIGH only if the LLM is confident, there is no tax-ID conflict and the deterministic
  score is at least 0.80. Tested with a fake LLM that answers "same" for every pair
  (`tests/test_agents.py::test_llm_cannot_merge_past_the_guardrail`).
- A drafted rule must name a real column and a supported rule type, and is dry-run on Silver before a
  steward can accept it.
- The steward assistant never shows `bank_account`.
- `LLM_MAX_CALLS_PER_RUN` (default 50) caps cost per run; failures and refusals fall back to rules.

## LLM providers

| `LLM_PROVIDER` | Needs | Default model |
|---|---|---|
| `none` | nothing | — |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-opus-5-5` (`LLM_MODEL` to change), low effort, server-side refusal fallback on |
| `azure_openai` | endpoint, key, deployment | your deployment (closest to Fabric AI Functions) |
| `ollama` | `docker compose --profile ollama up -d` then `docker compose exec ollama ollama pull llama3.2` | `llama3.2` (`OLLAMA_MODEL`) |

> The LLM providers have been tested only with a scripted fake client. Run one real provider before the
> demo and check `llm_calls` / `llm_failures` in the run history.

## Demo flow on the local stack

1. **Overview** → Run pipeline (or use the bootstrap run).
2. **Review queue** → pick a pair → Ask the steward assistant → Same vendor. Repeat ~20 times, then
   **Train matcher** (the model appears in MLflow).
3. **Rule studio** → "Invoice amount must not exceed 1,000,000" → Draft and dry-run → Accept.
4. **Overview** → Inject bad batch → Run pipeline → **Alerts & agents** shows AL01/AL02 with the cause.
5. **Executive spend** → before/after harmonization; then Remove bad batch and run again.

## Verified on 2026-10-04 (Docker Desktop, rules-only)

| Check | Result |
|---|---|
| Bootstrap run in the container | 52,450 records in 13 s; DQ score 70.5% → 99.0%; 3,103 golden vendors |
| 30 steward decisions → next run | review queue 201 → 171; recall 0.955 → 0.963 |
| Train matcher | MLflow run logged; `goldenrecord-matcher` v1 registered |
| Bad batch (3,000 invoices) | Alerts AL01 + AL02 raised; cause names R07, R06, A01 |
| Deploy kit without credentials | Tests pass, wheel 0.2.0 built, 5 notebooks exported; stops before `fab` |
| Test suite | 20 tests pass (agents, guardrail, API, every UI page) |
