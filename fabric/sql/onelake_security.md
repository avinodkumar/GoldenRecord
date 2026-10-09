# PII protection: from ingestion, not just at the gate

| Layer | What holds personal data | Control |
|---|---|---|
| `Files/landing` | Raw extracts (transient) | OneLake security role `pipeline-only`; files moved to a restricted archive after nb_01 |
| `pii_vault` table | Raw phone, email, bank account per record key | OneLake security role `pii-custodian` only (e.g. AP payments team) |
| Bronze, Silver, Gold | Masked values (`+91******3210`, `a***@apex.co.in`, `****1234`) and keyed tokens | Readable by engineers and stewards; tokens match equal values but cannot be reversed without the Key Vault key |
| Semantic model | No token or bank columns | Columns excluded; sensitivity label inherited |

Tokens are HMAC-SHA256 with a key held in Azure Key Vault (`goldenrecord-pii-token-key`), read at run time
with `notebookutils.credentials.getSecret`. Matching compares tokens, so dedup works without anyone seeing
raw values. Verified locally by `tests/test_agents.py::test_rules_only_run_builds_every_layer_without_raw_pii`.

## OneLake security roles (lh_goldenrecord → Manage OneLake security)

| Role | Members | Tables |
|---|---|---|
| `pii-custodian` | AP payments lead | `pii_vault` (read) |
| `data-steward` | Stewards | All tables except `pii_vault` |
| `analyst` | Report consumers | `gold_*` views only (through the certified semantic model) |
| `pipeline-only` | Workspace identity | `Files/landing`, write all |

## Purview (optional, where the tenant has it)

Sensitivity labels on the Lakehouse and semantic model, lineage across the MLVs, and a DSPM for AI
assessment. GoldenRecord does not depend on Purview: detection runs in MLV constraints and the agents,
and protection above is OneLake security plus tokenization.
