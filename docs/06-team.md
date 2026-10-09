# 06 · Team and ways of working

## Team GoldenRecord

| Name | Role | Owns |
|---|---|---|
| Vinod Atmakur | Product owner & quality architect (PO) | Scope, rule catalog, rule library, governance, storyline, pitch |
| Anand Topu | *[Role]* | *[Owns]* |
| Yogesh Godwade | *[Role]* | *[Owns]* |
| Koushik Das | *[Role]* | *[Owns]* |
| Ravi Chander Kanikala | *[Role]* | *[Owns]* |
| Dilip Divakaran | *[Role]* | *[Owns]* |

Roles to assign: data engineer (DE), AI/ML engineer (AI), Power BI developer (BI), QA & test data (QA), governance & security.

## RACI for the six deliverables

| Deliverable | PO | DE | AI | BI | QA |
|---|---|---|---|---|---|
| 1 Harmonization service, golden record | A | R | C | I | C |
| 2 AI matching notebook | A | C | R | I | C |
| 3 Review queue with write-back | A | I | C | R | C |
| 4 DQ rules (MLV) + Activator | R/A | C | R | I | C |
| 5 PII protection (tokens, OneLake security) | R/A | R | I | C | C |
| 6 Certified model + spend report | A | C | I | R | C |

R = responsible, A = accountable, C = consulted, I = informed.

## Cadence

- 15-minute stand-up daily; blockers first.
- Board: the story IDs in [03-roadmap.md](03-roadmap.md).
- Branches: `feature/<story-id>-short-name`; pull request with a passing `pytest` before merge.
- End of each sprint: 20-minute demo of what runs in Fabric, then update `metrics.json` numbers.
