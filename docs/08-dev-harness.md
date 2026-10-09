# 08 · Offline dev harness (not part of the solution)

The solution runs in Microsoft Fabric ([02-architecture.md](02-architecture.md)). This Docker stack exists
so the team can build, test and rehearse without a Fabric capacity, and as a fallback if the live
environment fails during the demo. It runs **the same agents and package** as the Fabric notebooks, on
open-source stand-ins.

```bash
cp .env.example .env
docker compose up -d --build
```

| URL | What |
|---|---|
| http://localhost:8501 | Steward UI (stand-in for the Power BI report and its translytical buttons) |
| http://localhost:8000/docs | Agent API |
| http://localhost:5000 | MLflow |

| Fabric item | Harness stand-in | Why a stand-in |
|---|---|---|
| OneLake + Lakehouse | Delta tables via delta-rs in a Docker volume | No capacity needed |
| Materialized lake views | Same rules evaluated by the Quality agent (`tests/test_fabric_sql.py` proves parity) | MLVs only run in Fabric |
| AI Functions | `LLM_PROVIDER=none` (deterministic fallbacks) or `azure_openai` | AI Functions only run in Fabric |
| Power BI + translytical task flows | Streamlit UI calling the agent API | Fabric-only |
| Activator | Sentinel agent (+ optional webhook) | Fabric-only |
| OneLake security | Not enforced; PII is still tokenized at ingestion | Fabric-only |
| Fabric Data Science MLflow | MLflow server container | Same API |

Deploy kit: `docker compose --profile deploy run --rm toolbox` runs the tests, builds the wheel for the Fabric
Environment, exports the notebooks in Fabric's format, and imports them with the Fabric CLI when
credentials are set.
