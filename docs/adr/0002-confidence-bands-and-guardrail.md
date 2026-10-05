# ADR 0002 · Confidence bands with a deterministic guardrail

**Status:** Accepted · 2026-09-30

## Context

The brief requires an LLM match decision with a confidence band and explanation per record. LLMs can
be confidently wrong, and a wrong merge silently corrupts the golden record and the spend report.

## Decision

- Three bands: HIGH (≥ 0.90) auto-merge, MEDIUM (0.70–0.90) human review, LOW (< 0.70) no match.
- The deterministic score is computed first for every pair. AI Functions review only the 0.50–0.90 grey zone.
- AI agreement can raise a pair to HIGH only if there is no tax-ID conflict and the deterministic score
  is at least 0.80. Otherwise the pair goes to MEDIUM.
- A steward "no_match" overrides HIGH.

## Consequences

- The LLM never has the last word on a merge; the demo line "AI proposes, rules decide" is literally true.
- AI cost is limited to the grey zone.
- Thresholds are configuration (`config.py`) and are retuned from steward labels (`nb_05`).
