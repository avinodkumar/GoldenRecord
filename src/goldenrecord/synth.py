"""Synthetic multi-ERP vendor and spend data with seeded defects and ground truth.

Three source systems describe an overlapping set of real vendors, each in its own
schema and formats. Defects are seeded at known rates and written to
truth/seeded_defects.csv so every metric on the Proof slide is measured against
ground truth.
"""
from __future__ import annotations

import random
import string
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .config import RAW_DIR, TRUTH_DIR
from .reference import CITIES, COUNTRIES

STEMS = [
    "Apex", "Summit", "Vertex", "Nimbus", "Crescent", "Pioneer", "Horizon", "Sterling", "Evergreen", "Harbor",
    "Falcon", "Orion", "Atlas", "Beacon", "Cobalt", "Delta", "Ember", "Fusion", "Granite", "Helix",
    "Indigo", "Jade", "Keystone", "Lumen", "Meridian", "Nova", "Onyx", "Pinnacle", "Quantum", "Radiant",
    "Sapphire", "Titan", "Unity", "Vanguard", "Willow", "Zenith", "Aurora", "Bluebird", "Cedar", "Dynamo",
    "Eagle", "Frontier", "Galaxy", "Heritage", "Ironwood", "Juniper", "Kestrel", "Lotus", "Maple", "Northstar",
    "Oakridge", "Prism", "Quest", "Redwood", "Silverline", "Trident", "Upland", "Vista", "Westfield", "Yukon",
    "Acorn", "Bridgeway", "Catalyst", "Driftwood", "Elevate", "Fortis", "Greenleaf", "Highland", "Insight", "Jupiter",
    "Kinetic", "Landmark", "Magnolia", "Nexus", "Olympus", "Paragon", "Quarry", "Riverstone", "Skyline", "Tidewater",
]
INDUSTRIES = [
    "Logistics", "Foods", "Technologies", "Pharma", "Textiles", "Engineering", "Consulting", "Electricals",
    "Packaging", "Chemicals", "Motors", "Steel", "Plastics", "Software", "Healthcare", "Builders", "Traders",
    "Exports", "Agro", "Energy", "Solar", "Paper", "Printing", "Security", "Staffing", "Facilities", "Telecom",
    "Media", "Travels", "Hospitality", "Automation", "Instruments", "Metals", "Polymers", "Retail",
    "Distributors", "Castings", "Fabrics", "Analytics", "Networks", "Labs", "Freight", "Supplies",
    "Components", "Services",
]
INDUSTRY_ABBREV = {"Technologies": "Tech", "Engineering": "Engg", "Services": "Svcs", "Pharma": "Pharmaceuticals",
                   "Distributors": "Dist", "Telecom": "Comms"}
LEGAL_FORMS = {"IN": ["Pvt Ltd", "Ltd"], "US": ["Inc", "Corp", "LLC"], "GB": ["Ltd", "PLC"],
               "DE": ["GmbH", "AG"], "SG": ["Pte Ltd"]}
LEGAL_VARIANTS = {"Pvt Ltd": ["Pvt. Ltd.", "Private Limited", "PVT LTD"], "Ltd": ["Ltd.", "Limited"],
                  "Inc": ["Inc.", "Incorporated"], "Corp": ["Corp.", "Corporation"], "LLC": ["L.L.C."],
                  "PLC": ["P.L.C."], "GmbH": ["G.m.b.H."], "AG": ["A.G."], "Pte Ltd": ["Pte. Ltd."]}
COUNTRY_WEIGHTS = {"IN": 0.45, "US": 0.25, "GB": 0.10, "DE": 0.10, "SG": 0.10}
EMAIL_TLD = {"IN": "co.in", "US": "com", "GB": "co.uk", "DE": "de", "SG": "com.sg"}
STREETS = ["Park", "Lake", "Station", "Market", "Church", "Mill", "Harbour", "Industrial", "Ring", "Hill"]
STREET_TYPES = ["Road", "Street", "Avenue", "Lane", "Way"]
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

# Vendor defects: (defect_type, probability, category, expected_rule)
VENDOR_DEFECTS = [
    ("tax_missing", 0.10, "rule", "R01"),
    ("tax_invalid", 0.06, "rule", "R02"),
    ("tax_fixable_format", 0.10, "standardize", None),
    ("country_invalid", 0.05, "rule", "R03"),
    ("email_invalid", 0.08, "rule", "R04"),
    ("city_alias", 0.20, "standardize", None),
    ("name_typo", 0.08, "match", None),
    ("name_abbrev", 0.08, "match", None),
]
DUP_IN_SOURCE_RATE = 0.06

# Invoice defects: (defect_type, probability, category, expected_rule)
INVOICE_DEFECTS = [
    ("amount_negative", 0.04, "rule", "R05"),
    ("amount_missing", 0.03, "rule", "R05"),
    ("amount_outlier", 0.03, "anomaly", "A01"),
    ("date_future", 0.04, "rule", "R06"),
    ("date_invalid", 0.03, "rule", "R06"),
    ("currency_invalid", 0.05, "rule", "R07"),
    ("orphan_vendor", 0.05, "rule", "R08"),
]
DUP_INVOICE_RATE = 0.04

START_DATE = date(2025, 1, 1)
END_DATE = date(2026, 6, 30)


@dataclass
class TrueVendor:
    true_id: str
    stem: str
    industry: str
    legal: str
    country: str
    city: str
    street: str
    tax_id: str
    phone_digits: str
    email: str
    bank_account: str
    base_amount: float
    records: list = field(default_factory=list)


def _rand_alnum(rng: random.Random, n: int) -> str:
    return "".join(rng.choices(string.ascii_uppercase + string.digits, k=n))


def _typo(rng: random.Random, text: str) -> str:
    # Keep the first four characters intact so the typo is a realistic, recoverable error.
    if len(text) < 6:
        return text
    i = rng.randrange(4, len(text) - 1)
    op = rng.choice(["swap", "drop", "double"])
    if op == "swap":
        return text[:i] + text[i + 1] + text[i] + text[i + 2:]
    if op == "drop":
        return text[:i] + text[i + 1:]
    return text[:i] + text[i] + text[i:]


def _make_true_vendors(rng: random.Random, n: int) -> list[TrueVendor]:
    combos = [(s, i) for s in STEMS for i in INDUSTRIES]
    if n > len(combos):
        raise ValueError(f"at most {len(combos)} distinct vendors supported")
    chosen = rng.sample(combos, n)
    countries = list(COUNTRY_WEIGHTS)
    weights = list(COUNTRY_WEIGHTS.values())
    vendors = []
    for idx, (stem, industry) in enumerate(chosen, start=1):
        country = rng.choices(countries, weights)[0]
        city = rng.choice(CITIES[country])[0]
        vendors.append(TrueVendor(
            true_id=f"TV{idx:05d}",
            stem=stem,
            industry=industry,
            legal=rng.choice(LEGAL_FORMS[country]),
            country=country,
            city=city,
            street=f"{rng.randint(1, 999)} {rng.choice(STREETS)} {rng.choice(STREET_TYPES)}",
            tax_id=country + _rand_alnum(rng, 10),
            phone_digits="".join(rng.choices(string.digits, k=10)),
            email=f"ap@{stem.lower()}{industry.lower()}.{EMAIL_TLD[country]}",
            bank_account="".join(rng.choices(string.digits, k=rng.randint(12, 16))),
            base_amount=round(rng.uniform(500, 50000), 2),
        ))
    return vendors


class _IdGen:
    def __init__(self):
        self.vendor = {"ERP_A": 100000, "ERP_B": 30000, "ERP_C": 0}
        self.invoice = {"ERP_A": 5100000000, "ERP_B": 0, "ERP_C": 0}

    def vendor_id(self, source: str) -> str:
        self.vendor[source] += 1
        n = self.vendor[source]
        return {"ERP_A": f"{n:010d}", "ERP_B": str(n), "ERP_C": f"V-{n:06d}"}[source]

    def invoice_no(self, source: str) -> str:
        self.invoice[source] += 1
        n = self.invoice[source]
        return {"ERP_A": str(n), "ERP_B": f"INV-{n:06d}", "ERP_C": f"C-INV-{n:06d}"}[source]


def _render_vendor(rng: random.Random, tv: TrueVendor, source: str, vendor_id: str, defects: list) -> dict:
    """Render one source record for a true vendor, applying seeded defects."""
    iso2 = tv.country
    name_country, iso3, cc, _ = COUNTRIES[iso2]
    applied = set()
    for dtype, p, _, _ in VENDOR_DEFECTS:
        if rng.random() < p:
            applied.add(dtype)
    # Tax defects are mutually exclusive.
    tax_defects = [d for d in ("tax_missing", "tax_invalid", "tax_fixable_format") if d in applied]
    for extra in tax_defects[1:]:
        applied.discard(extra)
    if "name_abbrev" in applied and tv.industry not in INDUSTRY_ABBREV:
        applied.discard("name_abbrev")
    if "city_alias" in applied and not dict(CITIES[iso2])[tv.city]:
        applied.discard("city_alias")

    industry = INDUSTRY_ABBREV[tv.industry] if "name_abbrev" in applied else tv.industry
    legal = rng.choice([tv.legal, *LEGAL_VARIANTS[tv.legal]])
    name = f"{tv.stem} {industry} {legal}"
    if "name_typo" in applied:
        name = _typo(rng, name)
    if source == "ERP_A":
        name = name.upper()

    city = rng.choice(dict(CITIES[iso2])[tv.city]) if "city_alias" in applied else tv.city

    tax = tv.tax_id
    if "tax_missing" in applied:
        tax = ""
    elif "tax_invalid" in applied:
        tax = tax[:7]
    elif "tax_fixable_format" in applied:
        tax = f"{tax[:2].lower()} {tax[2:6].lower()}-{tax[6:]}"
    elif source == "ERP_B":
        tax = f"{tax[:2]}-{tax[2:6]}-{tax[6:]}"

    email = tv.email.replace("@", " at ") if "email_invalid" in applied else tv.email
    d = tv.phone_digits
    phone = {"ERP_A": f"+{cc} {d[:5]} {d[5:]}", "ERP_B": f"({cc}) {d[:3]}-{d[3:6]}-{d[6:]}",
             "ERP_C": f"00{cc}{d}"}[source]
    if "country_invalid" in applied:
        country = {"ERP_A": "XX", "ERP_B": "Unknown", "ERP_C": "ZZZ"}[source]
    else:
        country = {"ERP_A": iso2, "ERP_B": name_country, "ERP_C": iso3}[source]

    for dtype, _, category, rule in VENDOR_DEFECTS:
        if dtype in applied:
            defects.append(("vendor", source, f"{source}:{vendor_id}", dtype, category, rule))

    return {"id": vendor_id, "name": name, "street": tv.street, "city": city, "country": country, "tax": tax,
            "phone": phone, "email": email, "bank": tv.bank_account}


def _format_vendor_row(source: str, r: dict) -> dict:
    if source == "ERP_A":
        return {"LIFNR": r["id"], "NAME1": r["name"], "STRAS": r["street"], "ORT01": r["city"], "LAND1": r["country"],
                "STCD1": r["tax"], "TELF1": r["phone"], "SMTP_ADDR": r["email"], "BANKN": r["bank"]}
    if source == "ERP_B":
        return {"VENDOR_ID": r["id"], "VENDOR_NAME": r["name"], "ADDRESS_LINE1": r["street"], "CITY": r["city"],
                "COUNTRY": r["country"], "TAX_REGISTRATION_NUM": r["tax"], "PHONE": r["phone"],
                "EMAIL": r["email"], "BANK_ACCOUNT_NUM": r["bank"]}
    return {"VendorAccountNumber": r["id"], "VendorOrganizationName": r["name"], "AddressStreet": r["street"],
            "AddressCity": r["city"], "AddressCountryRegionId": r["country"], "TaxExemptNumber": r["tax"],
            "PrimaryPhone": r["phone"], "PrimaryEmail": r["email"], "BankAccountNumber": r["bank"]}


def _format_date(source: str, d: date) -> str:
    if source == "ERP_A":
        return d.strftime("%Y%m%d")
    if source == "ERP_B":
        return f"{d.day:02d}-{MONTHS[d.month - 1]}-{d.year}"
    return d.isoformat()


def _format_amount(source: str, amount: float) -> str:
    return f"{amount:,.2f}" if source == "ERP_B" else f"{amount:.2f}"


def _format_invoice_row(source: str, inv: dict) -> dict:
    if source == "ERP_A":
        return {"BELNR": inv["no"], "LIFNR": inv["vendor"], "BLDAT": inv["date"], "WRBTR": inv["amount"],
                "WAERS": inv["currency"]}
    if source == "ERP_B":
        return {"INVOICE_NUM": inv["no"], "VENDOR_ID": inv["vendor"], "INVOICE_DATE": inv["date"],
                "INVOICE_AMOUNT": inv["amount"], "INVOICE_CURRENCY_CODE": inv["currency"]}
    return {"InvoiceId": inv["no"], "VendorAccount": inv["vendor"], "InvoiceDate": inv["date"],
            "InvoiceAmount": inv["amount"], "CurrencyCode": inv["currency"]}


BAD_BATCH_FILE = "invoices_bad_batch.csv"


def inject_bad_batch(raw_dir: Path = RAW_DIR, n: int = 3000, seed: int = 99,
                     truth_dir: Path | None = TRUTH_DIR) -> dict:
    """Drop a broken ERP_A extract next to the normal one (demo trigger for the Sentinel alert).

    Every row is wrong in one way: negative amount, unknown currency, future date, or an extreme outlier.
    """
    rng = random.Random(seed)
    vendors = pd.read_csv(Path(raw_dir) / "ERP_A" / "vendors.csv", dtype=str, keep_default_na=False)
    ids = vendors["LIFNR"].tolist()
    rows, kinds_log = [], []
    for i in range(n):
        kind = rng.choice(["negative", "currency", "future", "outlier"])
        kinds_log.append(kind)
        amount = round(rng.uniform(500, 50000), 2)
        rows.append({
            "BELNR": str(5199000000 + i),
            "LIFNR": rng.choice(ids),
            "BLDAT": "20280115" if kind == "future" else "20260301",
            "WRBTR": f"{-amount if kind == 'negative' else 5_000_000 + amount if kind == 'outlier' else amount:.2f}",
            "WAERS": "XXX" if kind == "currency" else "INR",
        })
    path = Path(raw_dir) / "ERP_A" / BAD_BATCH_FILE
    pd.DataFrame(rows).to_csv(path, index=False)
    defects_path = Path(truth_dir) / "seeded_defects.csv" if truth_dir else None
    if defects_path and defects_path.exists():
        rule = {"negative": ("amount_negative", "rule", "R05"), "currency": ("currency_invalid", "rule", "R07"),
                "future": ("date_future", "rule", "R06"), "outlier": ("amount_outlier", "anomaly", "A01")}
        extra = pd.DataFrame([("invoice", "ERP_A", f"ERP_A:{r['BELNR']}", *rule[k]) for r, k in zip(rows, kinds_log)],
                             columns=["entity", "source_system", "record_key", "defect_type", "category",
                                      "expected_rule"])
        existing = pd.read_csv(defects_path, dtype=str, keep_default_na=False)
        existing = existing[~existing["record_key"].str.startswith("ERP_A:5199")]
        pd.concat([existing, extra], ignore_index=True).to_csv(defects_path, index=False)
    return {"file": str(path), "rows": n}


def remove_bad_batch(raw_dir: Path = RAW_DIR) -> bool:
    path = Path(raw_dir) / "ERP_A" / BAD_BATCH_FILE
    if path.exists():
        path.unlink()
        return True
    return False


def generate(n_vendors: int = 3000, n_invoices: int = 45000, seed: int = 42,
             raw_dir: Path = RAW_DIR, truth_dir: Path = TRUTH_DIR) -> dict:
    """Generate raw ERP extracts and ground truth. Returns a summary dict."""
    rng = random.Random(seed)
    ids = _IdGen()
    true_vendors = _make_true_vendors(rng, n_vendors)

    vendor_rows = {s: [] for s in ("ERP_A", "ERP_B", "ERP_C")}
    truth_rows, defects = [], []
    all_vendor_refs = []  # (source, vendor_id, TrueVendor)

    for tv in true_vendors:
        n_sources = rng.choices([1, 2, 3], [0.45, 0.35, 0.20])[0]
        for source in rng.sample(["ERP_A", "ERP_B", "ERP_C"], n_sources):
            copies = 2 if rng.random() < DUP_IN_SOURCE_RATE else 1
            for copy in range(copies):
                vid = ids.vendor_id(source)
                rendered = _render_vendor(rng, tv, source, vid, defects)
                vendor_rows[source].append(_format_vendor_row(source, rendered))
                truth_rows.append((source, vid, tv.true_id))
                all_vendor_refs.append((source, vid, tv))
                if copy == 1:
                    defects.append(("vendor", source, f"{source}:{vid}", "dup_in_source", "match", None))

    invoice_rows = {s: [] for s in ("ERP_A", "ERP_B", "ERP_C")}
    span_days = (END_DATE - START_DATE).days
    for _ in range(n_invoices):
        source, vid, tv = rng.choice(all_vendor_refs)
        _, _, _, currency = COUNTRIES[tv.country]
        if rng.random() < 0.10:
            currency = "USD"
        amount = round(tv.base_amount * rng.lognormvariate(0, 0.4), 2)
        inv_date = START_DATE + timedelta(days=rng.randint(0, span_days))
        inv = {"no": ids.invoice_no(source), "vendor": vid, "date": _format_date(source, inv_date),
               "amount": _format_amount(source, amount), "currency": currency}
        key = f"{source}:{inv['no']}"

        applied = [d for d in INVOICE_DEFECTS if rng.random() < d[1]]
        # Amount defects are mutually exclusive, as are date defects.
        seen_groups = set()
        kept = []
        for d in applied:
            group = d[0].split("_")[0]
            if group in seen_groups:
                continue
            seen_groups.add(group)
            kept.append(d)
        for dtype, _, category, rule in kept:
            if dtype == "amount_negative":
                inv["amount"] = _format_amount(source, -amount)
            elif dtype == "amount_missing":
                inv["amount"] = ""
            elif dtype == "amount_outlier":
                inv["amount"] = _format_amount(source, amount * 100)
            elif dtype == "date_future":
                inv["date"] = _format_date(source, date(2027, 1, 1) + timedelta(days=rng.randint(0, 540)))
            elif dtype == "date_invalid":
                inv["date"] = {"ERP_A": "20251345", "ERP_B": "31-FEB-2025", "ERP_C": "2025-13-45"}[source]
            elif dtype == "currency_invalid":
                inv["currency"] = rng.choice(["", "XXX", "RS"] if tv.country == "IN" else ["", "XXX"])
            elif dtype == "orphan_vendor":
                inv["vendor"] = {"ERP_A": f"{9900000 + rng.randint(0, 99999):010d}",
                                 "ERP_B": str(990000 + rng.randint(0, 9999)),
                                 "ERP_C": f"V-9{rng.randint(0, 99999):05d}"}[source]
            defects.append(("invoice", source, key, dtype, category, rule))

        invoice_rows[source].append(_format_invoice_row(source, inv))
        if rng.random() < DUP_INVOICE_RATE:
            invoice_rows[source].append(_format_invoice_row(source, inv))
            defects.append(("invoice", source, key, "dup_invoice", "rule", "R09"))

    raw_dir = Path(raw_dir)
    truth_dir = Path(truth_dir)
    for source in ("ERP_A", "ERP_B", "ERP_C"):
        out = raw_dir / source
        out.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(vendor_rows[source]).to_csv(out / "vendors.csv", index=False)
        pd.DataFrame(invoice_rows[source]).to_csv(out / "invoices.csv", index=False)

    truth_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(truth_rows, columns=["source_system", "source_vendor_id", "true_vendor_id"]).to_csv(
        truth_dir / "vendor_truth.csv", index=False)
    defects_df = pd.DataFrame(defects, columns=["entity", "source_system", "record_key", "defect_type",
                                                "category", "expected_rule"])
    defects_df.to_csv(truth_dir / "seeded_defects.csv", index=False)

    n_vendor_rows = sum(len(v) for v in vendor_rows.values())
    n_invoice_rows = sum(len(v) for v in invoice_rows.values())
    defective_keys = defects_df.groupby("entity")["record_key"].nunique().to_dict()
    return {
        "true_vendors": n_vendors,
        "vendor_records": n_vendor_rows,
        "invoice_records": n_invoice_rows,
        "total_records": n_vendor_rows + n_invoice_rows,
        "vendor_records_with_defect": int(defective_keys.get("vendor", 0)),
        "invoice_records_with_defect": int(defective_keys.get("invoice", 0)),
        "seeded_defects": len(defects_df),
    }
