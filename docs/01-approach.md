# 01 · Solution approach

## Problem (from the brief)

50,000+ records from several ERPs, about half of them unusable. Duplicate vendors, invalid values and
inconsistent formats reach the executive spend report, and nobody trusts the numbers.

## What we build

GoldenRecord, a Fabric-native harmonization service that stops bad data before it reaches the report:
every record is standardized, checked against rules, matched across ERPs with an explained confidence
band, and only governed Gold data feeds a certified spend report.

## Principles

1. **AI proposes, rules decide.** AI Functions only judge the grey zone. A pair reaches Gold
   automatically only when the deterministic rules still agree.
2. **Measured, not claimed.** We generate the data ourselves with seeded defects and ground truth, so
   every metric (catch rate, match precision/recall, DQ score) is computed, not estimated.
3. **Humans own the uncertain cases, by root cause.** Issues are grouped into patterns; one steward decision
   becomes a versioned rule for every matching record (ADR 0007).
4. **Governed by default.** PII is tokenized from Bronze and raw values sit in a OneLake-security vault;
   Gold is the only layer the semantic model can read. Purview labels are added where available.
5. **Local core, Fabric shell.** Business logic lives in one tested Python package; notebooks are thin
   wrappers (see [ADR 0001](adr/0001-fabric-native-with-local-core.md)).

## Mapping to the six required deliverables

| # | Deliverable | Where it lives |
|---|---|---|
| 1 | Bronze/Silver/Gold, golden record, survivorship, stable master key | `nb_01`–`nb_04`; MLVs from `fabric_sql.py`; `survivorship.py` |
| 2 | LLM classification and matching: decision, confidence band, explanation | `nb_02` (mappings once per pattern), `nb_04` (grey-zone pairs); AI Functions |
| 3 | Human review queue in Power BI with write-back; decisions persisted | Pattern queue + translytical task flows (`fabric/functions`), versioned `rule_library` |
| 4 | 5+ DQ rules, scorecard, anomaly alerts | 9 MLV constraints + quarantine view; Isolation Forest; Activator; Purview optional |
| 5 | Sensitivity protection | Tokenization at ingestion, OneLake security (`fabric/sql/onelake_security.md`); Purview labels if available |
| 6 | Certified semantic model and executive spend report on Gold only | `gold_spend_certified`; `powerbi/README.md` |

See [00-positioning.md](00-positioning.md) for what is native Fabric and what GoldenRecord adds.

## Scope

In scope: vendor master and invoice spend from three ERP extracts (SAP-, Oracle- and Dynamics-style),
batch runs, one Fabric workspace.
Out of scope for the hackathon: real ERP connectors, streaming ingestion, multi-workspace deployment
pipelines, customer or material master data.
