# 05 · Matching and data quality design

## Data-quality rules

Nine rules in [`config/dq_rules.yaml`](../config/dq_rules.yaml) plus anomaly check **A01** (invoice amount
> 20× the vendor's median, with at least 3 invoices of history). Invoices failing R05–R09 or A01 are
quarantined with their reasons; vendor failures are recorded and invalid values are ignored by
survivorship. Purview configuration: [`purview/README.md`](../purview/README.md).

## Matching pipeline

1. **Blocking.** Only compare records that share a valid tax ID, a phone number, or country + the first
   four characters of the normalized name. This keeps comparisons at about 55K pairs instead of 15M.
2. **Deterministic score** (`matching.score_pair`):

   | Evidence | Score |
   |---|---|
   | Same valid tax ID | 0.6 + 0.4 × name similarity |
   | Conflicting valid tax IDs | 0.4 × name similarity (effectively never a match) |
   | Otherwise | 0.55 × name + 0.15 × same city + 0.15 × same phone + 0.15 × same email domain |

3. **Confidence bands.** HIGH ≥ 0.90 auto-merge · MEDIUM 0.70–0.90 human review · LOW < 0.70 no match.
4. **AI review of the grey zone (Fabric).** Pairs scoring 0.50–0.90 go through `ai.similarity` on names,
   `ai.classify` ("same vendor" / "different vendor") and `ai.generate_response` for a one-sentence
   steward explanation.
5. **Guardrail.** The AI can raise a pair to HIGH only if there is no tax-ID conflict and the deterministic
   score is at least 0.80. Otherwise the best it can do is MEDIUM (human review). See
   [ADR 0002](adr/0002-confidence-bands-and-guardrail.md).
6. **Clustering.** Union-find over merged pairs → golden records.
7. **Learning loop.** Steward decisions are stored in `steward_decisions`, merged on the next run, and
   used by `nb_05` to train a classifier tracked in MLflow.

## Baseline results (local, synthetic data, seed 42)

From `python -m goldenrecord all` on 2026-09-30 (5,600 vendor records, 46,850 invoices):

| Metric | First run | After steward review |
|---|---|---|
| Candidate pairs (HIGH / MEDIUM / LOW) | 3,366 / 201 / 51,520 | same |
| Match precision / recall (pairwise) | 1.00 / 0.955 | 1.00 / 1.00 |
| Golden vendors (true: 3,000) | 3,103 | 3,000 |
| Rule + anomaly catch rate | 0.994 | 0.994 |
| Amount outliers caught (A01) | 0.928 | 0.928 |
| False quarantine rate (clean invoices) | 0.0 | 0.0 |
| DQ score Silver → Gold | 0.705 → 0.990 | 0.705 → 0.993 |

**Caveat:** this synthetic data is easier than real data, and the deterministic matcher already solves
it. Story S2-06 adds harder cases (acronyms like "IBM" vs "International Business Machines", missing
tax IDs with name variants, transliterations) where AI similarity is needed, so the demo shows why the
AI layer matters.
