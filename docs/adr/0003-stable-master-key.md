# ADR 0003 · Stable master key via crosswalk reuse

**Status:** Accepted · 2026-09-30

## Context

Deliverable 1 requires a stable master key. Clusters change between runs as new records arrive and
stewards approve matches, so a key derived from cluster contents (for example a hash) would change too.

## Decision

Master keys are opaque sequence IDs (`GRV-000001`). Each run reads the previous `gold_vendor_xref`:

- A cluster reuses the most common previous key among its members.
- When a cluster splits, the largest part keeps the key; the others get new keys.
- When clusters merge, the merged cluster keeps the most common key; the other key is retired.
- New clusters get the next sequence number.

## Consequences

- Reports and downstream systems can rely on `master_key` across runs.
- Retired keys should be logged to a `master_key_history` table (backlog) so old references can be redirected.
