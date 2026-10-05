from datetime import date

import pandas as pd

from goldenrecord.matching import assign_band, cluster, score_pair
from goldenrecord.rules import load_rules, run_rules
from goldenrecord.survivorship import assign_master_keys


def _vendor(key, name, tax=None, city="Bengaluru", phone="+919876543210", domain="apex.co.in", country="IN"):
    return {"record_key": key, "vendor_name": name, "vendor_name_norm": name.upper(), "tax_id": tax,
            "city": city, "phone": phone, "email_domain": domain, "country_iso2": country,
            "email": f"ap@{domain}" if domain else None}


def test_rules_flag_each_seeded_problem():
    vendors = pd.DataFrame([
        _vendor("A:1", "Apex Logistics", tax="IN4F7K2P9Q1Z"),
        _vendor("A:2", "Nova Foods", tax=None),
        _vendor("A:3", "Onyx Steel", tax="IN123", country=None),
    ])
    invoices = pd.DataFrame({
        "record_key": ["A:10", "A:11", "A:12", "A:12"],
        "vendor_record_key": ["A:1", "A:1", "A:99", "A:1"],
        "amount": [100.0, -5.0, 10.0, 10.0],
        "invoice_date": [date(2025, 1, 1), date(2030, 1, 1), date(2025, 1, 1), date(2025, 1, 1)],
        "currency": ["INR", "INR", "XXX", "INR"],
    })
    failures, summary = run_rules(vendors, invoices, load_rules(), as_of=date(2026, 9, 30))
    flagged = set(zip(failures["rule_id"], failures["record_key"]))
    assert ("R01", "A:2") in flagged
    assert ("R02", "A:3") in flagged and ("R03", "A:3") in flagged
    assert ("R05", "A:11") in flagged and ("R06", "A:11") in flagged
    assert ("R07", "A:12") in flagged and ("R08", "A:12") in flagged and ("R09", "A:12") in flagged
    assert not any(k == "A:10" for _, k in flagged)
    assert len(summary) >= 5


def test_same_tax_id_is_high_band_and_conflicting_tax_is_low():
    a = _vendor("A:1", "APEX LOGISTICS", tax="IN4F7K2P9Q1Z")
    b = _vendor("B:1", "APEX LOGISTCS", tax="IN4F7K2P9Q1Z")
    c = _vendor("C:1", "APEX LOGISTICS", tax="IN0000000000")
    assert score_pair(a, b)["band"] == "HIGH"
    assert score_pair(a, c)["band"] == "LOW"
    assert score_pair(a, b)["explanation"].startswith("Same tax ID")


def test_band_thresholds():
    assert assign_band(0.95) == "HIGH"
    assert assign_band(0.80) == "MEDIUM"
    assert assign_band(0.50) == "LOW"


def test_golden_name_follows_the_majority_not_a_typo():
    from goldenrecord.survivorship import build_golden
    vendors = pd.DataFrame([
        {**_vendor("ERP_C:1", "Beacon Stele Inc"), "vendor_name_norm": "BEACON STELE"},
        {**_vendor("ERP_A:1", "BEACON STEEL INC"), "vendor_name_norm": "BEACON STEEL"},
        {**_vendor("ERP_B:1", "Beacon Steel Corp."), "vendor_name_norm": "BEACON STEEL"},
    ]).assign(source_system=lambda d: d["record_key"].str.split(":").str[0],
              source_vendor_id="1", street="1 Hill Road", bank_account="123")
    clusters = {k: "ERP_A:1" for k in vendors["record_key"]}
    gold, _ = build_golden(vendors, clusters)
    assert gold.loc[0, "vendor_name_norm"] == "BEACON STEEL"
    assert gold.loc[0, "vendor_name"] == "BEACON STEEL INC"


def test_master_keys_stay_stable_across_runs():
    first = cluster(["A:1", "B:1", "C:1"], [("A:1", "B:1")])
    keys1 = assign_master_keys(first, None)
    xref = pd.DataFrame({"record_key": list(first), "master_key": [keys1[first[k]] for k in first]})
    # A new record joins the A/B cluster on the second run.
    second = cluster(["A:1", "B:1", "C:1", "D:1"], [("A:1", "B:1"), ("B:1", "D:1")])
    keys2 = assign_master_keys(second, xref)
    assert keys2[second["D:1"]] == keys1[first["A:1"]]
    assert keys2[second["C:1"]] == keys1[first["C:1"]]
