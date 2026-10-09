# ADR 0005 · Build on native Fabric detection; own only remediation and resolution

**Status:** Accepted · 2026-10-09 · supersedes the multi-vendor stack (Great Expectations, Splink, Presidio, Streamlit, "Fabric or Databricks")

## Context

Reviewers pointed out that Fabric already detects and scores: materialized-lake-view constraints, Purview
data quality, Activator, AI Functions. A stack of external tools reads as indecision and earns no Fabric
credit, and rebuilding detection invites "you rebuilt Purview".

## Decision

- **Detection and scoring are native.** MLV `CONSTRAINT … ON MISMATCH DROP` generated from one rule catalog
  (`fabric_sql.py`), a per-source score view watched by Activator, SynapseML Isolation Forest for outlier scores.
  Purview is optional: used for labels, lineage and scorecards where a tenant has it, never a dependency.
- **GoldenRecord builds only what the platform lacks:** quarantine with per-row reasons, AI-authored fixes
  behind the guardrail, golden-record entity resolution with survivorship, and a pattern-level steward queue
  with a versioned rule library.
- **Experience** is Power BI with translytical task flows and User Data Functions. Streamlit stays only in
  the offline dev harness.
- **LLM** is Fabric AI Functions inside notebooks (no keys). The dev harness may use Azure OpenAI.
- **Privacy** is OneLake security roles plus tokenization with a Key Vault key, from Bronze onwards.

## Consequences

- Every production component is a Fabric item; the pitch can name them.
- The rules stay consistent across layers: `tests/test_fabric_sql.py` proves the generated constraints fail
  exactly the records the local engine fails.
- The ablation (`python -m goldenrecord ablation`) shows what native constraints alone deliver versus the full system.
