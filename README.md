# GoldenRecord

**Team GoldenRecord · Hackathon Track 02: GenAI Data Harmonization & Quality Guardrails**

> **Fabric tells you your data is bad; GoldenRecord fixes it.** It runs Fabric notebooks with AI Functions
> on top of materialized-lake-view constraints in OneLake, so that every bad record is quarantined with a
> reason, repaired by rules learned once, and resolved into one golden vendor. Stewards approve fixes by
> root cause in Power BI, through translytical task flows. Activator alerts when a source's quality drops.

## What it adds on top of Fabric

Native Fabric detects and scores; GoldenRecord builds only what the platform lacks
([docs/00-positioning.md](docs/00-positioning.md)):

1. **Quarantine with reasons.** MLV constraints drop bad rows; our quarantine view keeps them with the rules they failed.
2. **Fixes learned once.** AI Functions author a mapping or fix once per root cause; it is validated,
   versioned and reused deterministically. Reruns make zero AI calls.
3. **Golden records.** Entity resolution with survivorship and stable master keys; every merge explained
   and reversible.
4. **Pattern-level stewardship.** 14,006 issue records become 61 root-cause patterns (58 decisions), made in Power BI with
   translytical task flows.

PII is tokenized and masked from Bronze onwards; raw values live only in a OneLake-security-restricted vault.

## Measured (same seeded dataset, `python -m goldenrecord ablation`)

| | Native constraints only | GoldenRecord + 58 pattern decisions |
|---|---|---|
| Bad rows with a per-row reason | none (counters only) | all |
| Records repaired, with lineage | 0 | 1,185 |
| Duplicate vendors merged (of 1,743) | 0 | 1,727 |
| Gold spend on the correct vendor | split across 5,600 IDs | 99.1% |
| LLM calls per run | 0 | 0 (vs 107,525 for LLM-on-every-row) |

## Repository

| Path | What |
|---|---|
| `fabric/notebooks/` | The solution: nb_01 ingest → nb_02 learn and Silver → nb_03 native detection (MLVs, SynapseML) → nb_04 resolve and remediate → nb_05 apply steward inbox → nb_06 MLflow |
| `fabric/functions/`, `fabric/sql/` | User Data Functions for translytical task flows; SQL database inbox; OneLake security |
| `src/goldenrecord/` | Tested logic the notebooks call: privacy, mappings, rule library, patterns, agents, MLV SQL generation |
| `config/` | Rule catalog (drives MLV constraints, the agents and Purview) and alert rules |
| `powerbi/`, `activator/`, `purview/` | Configuration guides (Purview optional) |
| `docs/` | Positioning, architecture, roadmap, data model, break-it answers, ADRs |
| `Dockerfile`, `docker-compose.yml`, `ui/` | **Offline dev harness** only ([docs/08-dev-harness.md](docs/08-dev-harness.md)) |
| `tests/` | 25 tests, including the three break scenarios and constraint/engine parity |

## Run locally (dev harness)

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[stack,dev]"
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m goldenrecord ablation
docker compose up -d --build
```

## Documentation

[Pitch deck](docs/pitch/) · [00 Positioning](docs/00-positioning.md) · [01 Approach](docs/01-approach.md) · [02 Architecture](docs/02-architecture.md) ·
[03 Roadmap](docs/03-roadmap.md) · [04 Data model](docs/04-data-model.md) · [05 Matching and quality](docs/05-matching-and-quality.md) ·
[06 Team](docs/06-team.md) · [07 Demo script](docs/07-demo-script.md) · [08 Dev harness](docs/08-dev-harness.md) ·
[09 Break-it answers](docs/09-break-it-answers.md) · ADRs [0001](docs/adr/0001-fabric-native-with-local-core.md)–[0007](docs/adr/0007-pattern-queue-and-rule-library.md)
