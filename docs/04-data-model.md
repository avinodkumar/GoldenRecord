# 04 · Data model

## Source extracts (Bronze)

| Canonical field | ERP_A (SAP-style) | ERP_B (Oracle-style) | ERP_C (Dynamics-style) |
|---|---|---|---|
| source_vendor_id | `LIFNR` 0000100001 | `VENDOR_ID` 30001 | `VendorAccountNumber` V-000001 |
| vendor_name | `NAME1` (uppercase) | `VENDOR_NAME` | `VendorOrganizationName` |
| street / city | `STRAS` / `ORT01` | `ADDRESS_LINE1` / `CITY` | `AddressStreet` / `AddressCity` |
| country | `LAND1` ISO2 | `COUNTRY` full name | `AddressCountryRegionId` ISO3 |
| tax_id | `STCD1` | `TAX_REGISTRATION_NUM` (dashed) | `TaxExemptNumber` |
| phone | `TELF1` +91 98765 43210 | `PHONE` (91) 987-654-3210 | `PrimaryPhone` 00919876543210 |
| email | `SMTP_ADDR` | `EMAIL` | `PrimaryEmail` |
| bank_account | `BANKN` | `BANK_ACCOUNT_NUM` | `BankAccountNumber` |
| invoice_no | `BELNR` | `INVOICE_NUM` | `InvoiceId` |
| invoice_date | `BLDAT` YYYYMMDD | `INVOICE_DATE` DD-MON-YYYY | `InvoiceDate` ISO |
| amount / currency | `WRBTR` / `WAERS` | `INVOICE_AMOUNT` (1,234.56) / `INVOICE_CURRENCY_CODE` | `InvoiceAmount` / `CurrencyCode` |

## Silver

**silver_vendor**: `record_key` (`<source>:<id>`, PK), `source_system`, `source_vendor_id`, `vendor_name`,
`vendor_name_norm`, `street`, `city` (alias-resolved), `country_raw`, `country_iso2`, `tax_id`
(uppercase alphanumeric), `phone` (E.164-like), `email`, `email_domain`, `bank_account` 🔒.

**silver_invoice**: `record_key` (`<source>:<invoice_no>`), `source_system`, `invoice_no`, `source_vendor_id`,
`vendor_record_key` (FK → silver_vendor), `invoice_date_raw`, `invoice_date`, `amount`, `currency`.

**silver_dq_failures**: `rule_id`, `entity`, `record_key`. **silver_match_pairs**: `left_key`, `right_key`,
feature columns, `score`, `band`, `explanation`, `ai_similarity`, `ai_decision`, `decided_by`.

## Gold

**gold_vendor** (one row per real vendor): `master_key` (PK, `GRV-000001`), `vendor_name`, `vendor_name_norm`,
`tax_id`, `country_iso2`, `city`, `street`, `phone`, `email`, `bank_account` 🔒, `source_systems`, `member_count`.

**gold_vendor_xref**: `master_key`, `record_key`, `source_system`, `source_vendor_id`. Every Silver vendor
record maps to exactly one master key.

**gold_spend_fact**: `record_key`, `master_key`, `source_system`, `invoice_no`, `invoice_date`, `currency`,
`amount`, `amount_usd`. Only invoices passing R05–R09 and A01.

**quarantine_invoice**: Silver invoice columns plus `failed_rules`. **review_queue**: MEDIUM-band pairs awaiting a decision.
**steward_decisions**: `left_key`, `right_key`, `decision` (`match`/`no_match`), `reviewer`, `decided_at`.

🔒 = labelled Highly Confidential; hidden from the semantic model.

## Survivorship rules

| Attribute | Rule |
|---|---|
| vendor_name | Most common normalized name across members; display form from the highest-priority source using it |
| street, bank_account | First non-empty value by source priority: ERP_C → ERP_A → ERP_B |
| tax_id | Most frequent value that passes R02 |
| country_iso2, city, phone | Most frequent non-empty value |
| email | First value (by priority) that passes R04 |

## Master key stability

See [ADR 0003](adr/0003-stable-master-key.md). On each run, a cluster reuses the most common previous
master key among its members; new clusters get the next sequence number. Tested in
`tests/test_rules_and_matching.py::test_master_keys_stay_stable_across_runs`.
