# GoldenRecord – AI Data Quality Gatekeeper

**Team GoldenRecord · Hackathon Track 02: GenAI Data Harmonization & Quality Guardrails**

> No bad record reaches the boardroom. Every rejected record comes with a reason, a fix and an audit trail.

A Microsoft Fabric solution that harmonizes vendor and spend data from three ERPs: Bronze → Silver → Gold,
AI matching with confidence bands and explanations, a human review loop, Purview data-quality rules,
Activator alerts, and a certified executive spend report that reads only governed Gold data.

## Quick start: Docker (full stack with agents)

```bash
cp .env.example .env        # optional: pick an LLM provider; default runs rules-only
docker compose up -d --build
```

Open the control room at http://localhost:8501, the agent API at http://localhost:8000/docs and MLflow
at http://localhost:5000. Six agents run the pipeline: Profiler, Quality, Matcher, Gatekeeper, Steward
assistant and Sentinel. See [docs/08-agents-and-local-stack.md](docs/08-agents-and-local-stack.md).

Deploy to Fabric (builds the wheel, exports the notebooks, imports them with the Fabric CLI):

```bash
docker compose --profile deploy run --rm toolbox
```

## Quick start: Python only (no Docker)

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m goldenrecord all
.venv/Scripts/python -m pytest -q
```

`all` generates the synthetic ERP extracts (about 52K records with seeded defects), runs the pipeline,
simulates a steward reviewing the queue, runs again, and prints the metrics. Outputs land in `data/`
(`data/reports/metrics.json` feeds the Proof slide).

Individual steps: `python -m goldenrecord generate | run | review`.

## Repository map

| Path | What |
|---|---|
| `src/goldenrecord/` | Tested core logic: synthetic data, standardization, rules, matching, survivorship, evaluation |
| `src/goldenrecord/agents/` | Profiler, Quality, Matcher, Gatekeeper, Steward assistant, Sentinel, orchestrator |
| `src/goldenrecord/api.py`, `ui/app.py` | Agent API (FastAPI) and control-room UI (Streamlit) |
| `Dockerfile`, `docker-compose.yml`, `deploy/` | Local stack, Fabric deploy toolbox |
| `fabric/notebooks/` | Fabric notebooks nb_01–nb_05 (thin wrappers over the package + AI Functions) |
| `config/dq_rules.yaml` | Data-quality rule catalog, mirrored in Purview |
| `purview/`, `activator/`, `powerbi/` | Configuration guides for each Fabric and Purview item |
| `docs/` | Approach, architecture, roadmap, data model, matching design, team, demo script, ADRs |
| `tests/` | Unit and end-to-end smoke tests |

## Documentation

1. [Solution approach](docs/01-approach.md): principles and the six required deliverables
2. [Architecture](docs/02-architecture.md): flow diagram, layers, runtime sequence
3. [Roadmap](docs/03-roadmap.md): two-week plan, milestones, backlog, risks
4. [Data model](docs/04-data-model.md): source mappings, Silver/Gold schemas, survivorship
5. [Matching and quality](docs/05-matching-and-quality.md): rules, bands, AI guardrail, baseline results
6. [Team](docs/06-team.md): roles, RACI, cadence
7. [Demo script](docs/07-demo-script.md)
8. [Agents and local stack](docs/08-agents-and-local-stack.md): Docker stand-ins, agents, guardrails, demo flow
9. ADRs: [Fabric + local core](docs/adr/0001-fabric-native-with-local-core.md) ·
   [Bands and guardrail](docs/adr/0002-confidence-bands-and-guardrail.md) ·
   [Stable master key](docs/adr/0003-stable-master-key.md) ·
   [Local stack stand-ins](docs/adr/0004-local-stack-stand-ins.md)

## Status

Milestone M0 (local core) and the local Docker stack with agents are done. Next: Fabric foundation
(Sprint 1 stories S1-04 to S1-08 in the roadmap), then run one real LLM provider.
