# ADR 0006 · The LLM authors mappings and rules once per pattern; execution is deterministic

**Status:** Accepted · 2026-10-09

## Context

Sending 50K records (and their candidate pairs) through an LLM on every run costs about 107,525 calls a run
on our dataset. It is slow, and non-deterministic: the same record can be answered differently tomorrow,
which breaks auditability.

## Decision

- The Profiler collects **distinct** unknown values per domain (city, name token, currency) and asks the LLM
  once per batch of 40 values to map each one to a **known canonical value**. Answers are cached
  (`llm_mapping_cache`), so the same value is never asked twice.
- A guardrail validates every proposal: the target must exist (a known city, a core name word, a supported
  currency, or "drop: misspelt legal form"). Validated proposals with confidence ≥ 0.90 are auto-approved
  into the versioned rule library. Everything else becomes a steward pattern.
- Deterministic rules go first (fuzzy match to the core vocabulary), so the LLM only sees what rules cannot
  resolve.
- Pair judgements are cached by an evidence fingerprint (`llm_pair_cache`). Pairs covered by an approved
  match rule are never sent to the LLM.
- Standardization and matching then use plain lookups from the library: same input, same output.

## Consequences

- Rerunning with no new values costs **zero** LLM calls, and the output is identical
  (`test_llm_authors_mappings_once_then_reruns_are_deterministic_and_free`).
- Every mapping in use has an author (`rule`, `llm`, `steward`, `auto-policy`), a confidence and a version.
- New values still cost a call the first time they appear; costs scale with variety, not volume.
