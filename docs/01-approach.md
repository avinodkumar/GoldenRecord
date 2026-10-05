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
3. **Humans own the uncertain cases.** Medium-band pairs go to a steward; each decision becomes a
   training label.
4. **Governed by default.** Gold is the only layer the semantic model can read; labels, DLP and
   DSPM for AI protect sensitive vendor data.
5. **Local core, Fabric shell.** Business logic lives in one tested Python package; notebooks are thin
   wrappers (see [ADR 0001](adr/0001-fabric-native-with-local-core.md)).

## Mapping to the six required deliverables

| # | Deliverable | Where it lives |
|---|---|---|
| 1 | Bronze/Silver/Gold, golden record, survivorship, stable master key | `nb_01`, `nb_02`, `nb_04`; `standardize.py`, `survivorship.py` |
| 2 | LLM classification and matching: decision, confidence band, explanation | `nb_03_ai_match`; `matching.py` |
| 3 | Human review queue in Power BI with write-back; labels persisted | `powerbi/README.md`; `steward_decisions`; `nb_05` |
| 4 | 5+ active Purview DQ rules, scorecard, Activator alerts | `config/dq_rules.yaml`; `purview/README.md`; `activator/README.md` |
| 5 | Sensitivity labels; DSPM for AI screenshot | `purview/README.md` §3 |
| 6 | Certified semantic model and executive spend report on Gold only | `powerbi/README.md` |

## Scope

In scope: vendor master and invoice spend from three ERP extracts (SAP-, Oracle- and Dynamics-style),
batch runs, one Fabric workspace.
Out of scope for the hackathon: real ERP connectors, streaming ingestion, multi-workspace deployment
pipelines, customer or material master data.
