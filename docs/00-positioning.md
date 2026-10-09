# 00 · Positioning: why GoldenRecord, and why this team

## The pitch in one sentence

> **Fabric tells you your data is bad; GoldenRecord fixes it.** It runs Fabric notebooks with AI Functions
> on top of materialized-lake-view constraints in OneLake, so that every bad record is quarantined with a
> reason, repaired by rules learned once, and resolved into one golden vendor. Stewards approve fixes by
> root cause in Power BI, through translytical task flows. Activator alerts when a source's quality drops.

**Headline:** the guardrail loop: detect → explain → fix safely → steward approves → rule learned.
**Supporting proof:** the golden record. Entity resolution with survivorship is where the fixes show up
in money (spend on the right vendor).

## Build on Fabric, not beside it

Microsoft already detects and scores. GoldenRecord does not rebuild that. It adds the remediation and
resolution layer that the native tools do not provide.

| Job | Native Fabric / Microsoft (we use it) | GoldenRecord adds |
|---|---|---|
| Detect | MLV `CONSTRAINT … CHECK … ON MISMATCH DROP`, generated from one rule catalog | A **quarantine view with the failed rule IDs per row**. Native MLVs only count drops |
| Score | Per-source score view (MLV) → Activator; Purview DQ scorecard where available | Scores tied to patterns and fixes, not just a red dashboard |
| Fix | — | **Fixes authored once per root cause** (AI or rules), validated, versioned, applied with lineage (`fixed_by`) |
| Resolve | — (Power Query fuzzy merge is a join, not MDM) | **Golden records**: blocking, scoring, AI for the grey zone only, survivorship, stable master keys, explain and unmerge |
| Steward | — | **Pattern-level queue**: one click fixes thousands of records, through translytical task flows |
| Govern | OneLake security roles, Key Vault, Purview labels and lineage (optional) | PII tokenized at ingestion; raw values only in a restricted vault |
| AI | Fabric AI Functions (built-in model, no keys) | Used to author mappings and judge new grey-zone pairs, **never row by row** |

Purview is optional by design. Its data-quality features need a Purview account in the data's region and
separate billing, so detection runs in MLV constraints and the agents, with the same rules. Where a
tenant has Purview, the same rule IDs are configured there for the governance scorecard.

## Our point of view: why data-quality fixes usually fail

1. **Detection without remediation.** Dashboards turn red and nobody owns the fix. Rules that only
   `DROP` make it worse: the bad rows disappear silently, and so does the spend attached to them.
2. **Fixes do not persist.** Someone cleans a spreadsheet; the next load brings the same garbage back.
   A fix that is not turned into a rule is a fix you will make again next month.
3. **Record-by-record review does not scale.** 25,000 issues and a review screen is a backlog, not a process.
4. **Dedup without survivorship.** Records get merged, but the wrong attributes win (a typo becomes the
   golden name), and there is no way to see or undo why two records were merged.
5. **LLM on every row.** Slow, costly and non-deterministic: the same record can get a different answer
   tomorrow, so nothing is auditable.

GoldenRecord answers each one: quarantine with reasons (1), a versioned rule library (2), a pattern queue
(3), survivorship plus merge lineage and unmerge (4), and an LLM that authors rules once per pattern (5).

## Measured on the same seeded dataset

`python -m goldenrecord ablation`: seed 42, 52,438 records, 3,000 true vendors (1,743 of them held in 2+ records).

| | A. Native constraints only | B. GoldenRecord, rules only | C. B + one round of pattern approvals | D. LLM on every row |
|---|---|---|---|---|
| Bad invoices removed from Gold | 12,164 | 12,164 | 11,228 (936 repaired instead) | – |
| …with a per-row reason | none (10 counters) | all | all | – |
| Records repaired, with lineage | 0 | 0 | **1,185** | – |
| Duplicate vendors merged (of 1,743) | 0 | 1,549 | **1,727** | – |
| Vendors resolved exactly (of 3,000) | 1,257 | 2,806 | **2,984** | – |
| Match precision / recall | – / 0 | 1.00 / 0.915 | **1.00 / 0.992** | not measured |
| Gold spend on the correct vendor | split over 5,600 IDs | 90.5% | **99.1%** | – |
| Steward work | none possible | 61 patterns, top 10 = 81% of issues | **58 decisions** | – |
| LLM calls per run | 0 | 0 | 0 | 107,525 |
| Same output on rerun | yes | yes | yes | no |

Honest notes: C simulates a steward approving each proposed pattern once. For the 11 unknown city aliases
(Bombay, Madras…) the simulated steward picks the right city; with AI Functions these are proposed
automatically. D's accuracy needs a live AI Functions run (roadmap S2-03). The data is synthetic, and
harder cases (acronyms, transliteration) are roadmap S2-06.

## What we have seen in real data-quality work

> Draft for the team to confirm or replace. Keep only what is true for us.

- **Vinod (quality architect, payments, fintech and healthcare):** *[one real example: e.g. a vendor or
  payee master where the same counterparty existed under several IDs and payments or reporting broke]*
- *[Member 2: one example of a fix that came back on the next load]*
- *[Member 3: one example of a merge that should not have happened, and how long it took to unwind]*

These shaped three design choices: fixes become rules (not edits), merges are explainable and
reversible, and stewards work on root causes, not rows.

## Who else is likely to propose something similar, and where we beat them

| Likely approach | What they will show | Where GoldenRecord wins (measured above) |
|---|---|---|
| **"Purview + MLV" configuration** | Rules, scores, alerts, all native | They detect; they do not repair (0 records), resolve (0 duplicates merged) or explain drops. We use the same native detection *and* fix on top |
| **"LLM cleanser"** (AI Functions over every row) | Impressive single-record fixes | 107,525 calls a run vs our 0 on steady state; non-deterministic; no audit trail or rollback |
| **"Fuzzy dedup"** (Power Query fuzzy merge or a matching library) | Duplicates found | No survivorship, no stable keys, no explain or unmerge, no guardrail against a false merge |

## The team

| Member | Role | Relevant experience (one line) |
|---|---|---|
| Vinod Atmakur | Product owner & quality architect | 20+ years in delivery and quality architecture across payments, fintech and healthcare *(confirm)* |
| Anand Topu | *[Role]* | *[one line]* |
| Yogesh Godwade | *[Role]* | *[one line]* |
| Koushik Das | *[Role]* | *[one line]* |
| Ravi Chander Kanikala | *[Role]* | *[one line]* |
| Dilip Divakaran | *[Role]* | *[one line]* |
