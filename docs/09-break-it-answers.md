# 09 · "Try to break it": the three scenarios, with mechanisms and proof

Each answer is a feature with a passing test in `tests/test_agents.py`.

## 1. A plain-English rule that the system generates wrongly

*"Invoice amount must not exceed 1,000" (the steward meant 1,000,000). How do you stop it quarantining half the table?*

| Guard | What happens |
|---|---|
| Validation | The draft must name a real column and a supported rule type, or it is refused |
| Impact preview | Before saving: records that would fail, fail rate, broken down by ERP source, sample keys |
| Blast-radius limit | Failing more than **5%** of the table blocks the rule; saving needs an explicit override |
| Shadow mode | An accepted rule only **flags**; it quarantines nothing until a steward promotes it |
| Rollback | Rules live in the versioned rule library; retiring the item removes it from the next run |

In Fabric the same rule becomes one more MLV `CONSTRAINT` only after promotion, so a bad rule never reaches
the constraint layer. Test: `test_scenario_wrong_rule_is_previewed_blocked_shadowed_and_rolled_back`.

## 2. A false merge of two different companies

*How do you detect it, and can you undo it?*

- **Prevention:** a pair with two different valid tax IDs cannot reach the HIGH band, whatever the AI says.
- **Detection:** after every run, each golden record is checked for two valid tax IDs, two countries, two bank
  accounts (by token) or dissimilar names. Suspects go to `gold_cluster_alerts`, and Activator rule AL05 fires.
- **Explanation:** `gold_merge_edges` records every merge with its reason: the rule score, an AI verdict, a
  library match rule, or a named steward. "Explain" on a golden record lists them.
- **Undo:** "Unmerge" adds versioned cannot-link items. The next run separates the records. The larger
  side keeps the master key, the other gets a new one, and spend is re-attributed automatically because
  the certified spend view joins on the cross-reference. The cannot-link holds on every future run.

Test: `test_scenario_false_merge_is_detected_and_undone`.

## 3. "About 25K bad records and the demo shows three. How does a steward cope?"

Issues are grouped by root cause, and one decision covers the whole group, now and in future loads:

| Pattern type | Example | One click does |
|---|---|---|
| Record fix | ERP_B: 320 invoices with blank currency | Sets currency from the vendor's country; every fixed row records `fixed_by` |
| Mapping batch | 92 name-token typo corrections (split into confident and uncertain bundles) | Adds them to the library in one version |
| Value mapping | 106 records with city "Calcutta" | Maps to Kolkata for good |
| Match rule | 144 pairs: no tax ID on one side, same name, phone and email domain | Merges all current and future pairs with that evidence |
| Acknowledge | 2,266 invoices whose vendor ID is not in the master | Keeps them quarantined, notifies each source owner, closes the pattern |

Measured: **14,006 issue records → 61 patterns; the top 10 cover 81%. After 58 decisions, 8 patterns
remain**, 1,185 records are repaired, and duplicate vendors resolved rise from 1,549 to 1,727 of 1,743.

### "Steward decisions grow the rule library": the mechanism

Every decision appends an item to `rule_library` (value mapping, record fix, match rule, data-quality rule,
acknowledgement or cannot-link). Each approval batch increments `library_version`. Each run records the
version it used, and each merge edge and fixed record names the item that caused it. Retiring an item is
itself a new version, so rollback is auditable. Test: `test_scenario_thousands_of_issues_become_a_short_pattern_queue`.
