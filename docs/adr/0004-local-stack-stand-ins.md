# ADR 0004 · Local Docker stack with open-source stand-ins for Fabric services

**Status:** Accepted · 2026-10-04

## Context

The team wants to build and demo the whole solution, including the agents, before Fabric access is
available. Fabric, Purview, Activator and Power BI cannot run in containers.

## Decision

Ship a `docker compose` stack where each Fabric piece has an open-source stand-in (table in
[08-agents-and-local-stack.md](../08-agents-and-local-stack.md)): Delta Lake tables via delta-rs for
the Lakehouse, a FastAPI agent service for the pipeline and notebooks, Streamlit for the reports and
write-back, an MLflow server for Data Science, and the Sentinel agent for Activator. A `toolbox` image
with the Fabric CLI builds the wheel and deploys the notebooks when Fabric access arrives.

The LLM is pluggable (`none`, `anthropic`, `azure_openai`, `ollama`), and every agent has a
deterministic fallback, so the stack also runs offline.

## Consequences

- One codebase: the agents and the Fabric notebooks call the same `goldenrecord` functions.
- The demo can run fully locally if Fabric is late or unavailable on the day.
- The stand-ins are not evidence for the six Fabric deliverables; judges still need the Fabric,
  Purview and Power BI screenshots (roadmap Sprints 2–4).
- Two runtimes to keep aligned: changes to the package must be rebuilt into both the Docker image and
  the Fabric Environment wheel (`docker compose --profile deploy run --rm toolbox` does both builds).
