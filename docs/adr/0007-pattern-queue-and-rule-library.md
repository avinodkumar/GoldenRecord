# ADR 0007 · Pattern-level stewardship and a versioned rule library

**Status:** Accepted · 2026-10-09

## Context

"Half of 50K is garbage" means about 25K issues. A record-by-record review queue cannot cope, and the
claim that "steward decisions grow the rule library" needed a concrete mechanism with versioning.

## Decision

- **Patterns, not records.** After each run the Steward agent groups every open issue by root cause:
  rule × signature (e.g. "currency (blank)"), mapping proposals, and match evidence signatures. Each pattern
  carries one proposed library item and the number of records it affects. Acknowledgements group the same
  root cause across sources; fixes stay scoped to one source.
- **One decision, every record, every future load.** Approving a pattern appends its item to
  `rule_library`: value mapping, record fix, match rule, acknowledgement, data-quality rule or cannot-link.
- **Versioning.** Each approval batch increments `library_version`; retiring an item is a new version.
  Each run records the version it used; fixed records (`fixed_by`) and merge edges (`reason`) name the item
  responsible. Rollback = retire.
- **Safety.** New data-quality rules start in shadow mode, behind a 5% blast-radius limit. False merges are
  flagged by consistency checks and undone with cannot-links.

## Consequences

- Seeded dataset: 14,006 issue records → 61 patterns (top 10 = 81% of issues). 58 decisions leave
  8 patterns, repair 1,185 records and lift duplicate-vendor resolution from 1,549 to 1,727 of 1,743.
- In Fabric the queue is a Power BI page; approve and reject are data function buttons (User Data Functions
  writing to a Fabric SQL database, applied by `nb_05`).
