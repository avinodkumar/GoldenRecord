"""Silver layer: map each ERP schema to one canonical model and standardize formats."""
from __future__ import annotations

import re
from datetime import datetime

import pandas as pd

from .reference import CITY_ALIASES, LEGAL_TOKENS, NAME_ABBREVIATIONS, country_to_iso2

SOURCE_SCHEMAS = {
    "ERP_A": {
        "vendors": {"LIFNR": "source_vendor_id", "NAME1": "vendor_name", "STRAS": "street", "ORT01": "city_raw",
                    "LAND1": "country_raw", "STCD1": "tax_id_raw", "TELF1": "phone_raw", "SMTP_ADDR": "email_raw",
                    "BANKN": "bank_account"},
        "invoices": {"BELNR": "invoice_no", "LIFNR": "source_vendor_id", "BLDAT": "invoice_date_raw",
                     "WRBTR": "amount_raw", "WAERS": "currency_raw"},
        "date_format": "%Y%m%d",
    },
    "ERP_B": {
        "vendors": {"VENDOR_ID": "source_vendor_id", "VENDOR_NAME": "vendor_name", "ADDRESS_LINE1": "street",
                    "CITY": "city_raw", "COUNTRY": "country_raw", "TAX_REGISTRATION_NUM": "tax_id_raw",
                    "PHONE": "phone_raw", "EMAIL": "email_raw", "BANK_ACCOUNT_NUM": "bank_account"},
        "invoices": {"INVOICE_NUM": "invoice_no", "VENDOR_ID": "source_vendor_id", "INVOICE_DATE": "invoice_date_raw",
                     "INVOICE_AMOUNT": "amount_raw", "INVOICE_CURRENCY_CODE": "currency_raw"},
        "date_format": "%d-%b-%Y",
    },
    "ERP_C": {
        "vendors": {"VendorAccountNumber": "source_vendor_id", "VendorOrganizationName": "vendor_name",
                    "AddressStreet": "street", "AddressCity": "city_raw", "AddressCountryRegionId": "country_raw",
                    "TaxExemptNumber": "tax_id_raw", "PrimaryPhone": "phone_raw", "PrimaryEmail": "email_raw",
                    "BankAccountNumber": "bank_account"},
        "invoices": {"InvoiceId": "invoice_no", "VendorAccount": "source_vendor_id", "InvoiceDate": "invoice_date_raw",
                     "InvoiceAmount": "amount_raw", "CurrencyCode": "currency_raw"},
        "date_format": "%Y-%m-%d",
    },
}


def _blank_to_none(value):
    if not isinstance(value, str):
        return None
    s = value.strip()
    return s or None


def normalize_name(name: str | None) -> str | None:
    """Uppercase, drop punctuation and legal-form tokens, expand abbreviations."""
    if not isinstance(name, str) or not name:
        return None
    s = name.upper().replace(".", "")
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    tokens = [NAME_ABBREVIATIONS.get(t, t) for t in s.split()]
    tokens = [t for t in tokens if t not in LEGAL_TOKENS]
    return " ".join(tokens) or None


def clean_tax_id(value: str | None) -> str | None:
    value = _blank_to_none(value)
    if value is None:
        return None
    return re.sub(r"[^A-Za-z0-9]", "", value).upper() or None


def clean_phone(value: str | None) -> str | None:
    value = _blank_to_none(value)
    if value is None:
        return None
    digits = re.sub(r"\D", "", value)
    if digits.startswith("00"):
        digits = digits[2:]
    return f"+{digits}" if len(digits) >= 8 else None


def clean_city(value: str | None) -> str | None:
    value = _blank_to_none(value)
    if value is None:
        return None
    return CITY_ALIASES.get(value.upper(), value.title())


def email_domain(email: str | None) -> str | None:
    if not isinstance(email, str) or "@" not in email:
        return None
    return email.rsplit("@", 1)[1].lower()


def parse_date(value: str | None, fmt: str):
    value = _blank_to_none(value)
    if value is None:
        return None
    try:
        return datetime.strptime(value.title() if "%b" in fmt else value, fmt).date()
    except ValueError:
        return None


def parse_amount(value: str | None) -> float | None:
    value = _blank_to_none(value)
    if value is None:
        return None
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def standardize_vendors(raw: pd.DataFrame, source: str) -> pd.DataFrame:
    df = raw.rename(columns=SOURCE_SCHEMAS[source]["vendors"]).copy()
    df = df.map(_blank_to_none)
    out = pd.DataFrame({
        "record_key": source + ":" + df["source_vendor_id"],
        "source_system": source,
        "source_vendor_id": df["source_vendor_id"],
        "vendor_name": df["vendor_name"].map(lambda v: " ".join(v.split()) if isinstance(v, str) else None),
        "vendor_name_norm": df["vendor_name"].map(normalize_name),
        "street": df["street"],
        "city": df["city_raw"].map(clean_city),
        "country_raw": df["country_raw"],
        "country_iso2": df["country_raw"].map(country_to_iso2),
        "tax_id": df["tax_id_raw"].map(clean_tax_id),
        "phone": df["phone_raw"].map(clean_phone),
        "email": df["email_raw"].map(lambda v: v.lower() if isinstance(v, str) else None),
        "bank_account": df["bank_account"],
    })
    out["email_domain"] = out["email"].map(email_domain)
    return out


def standardize_invoices(raw: pd.DataFrame, source: str) -> pd.DataFrame:
    schema = SOURCE_SCHEMAS[source]
    df = raw.rename(columns=schema["invoices"]).copy()
    df = df.map(_blank_to_none)
    fmt = schema["date_format"]
    return pd.DataFrame({
        "record_key": source + ":" + df["invoice_no"],
        "source_system": source,
        "invoice_no": df["invoice_no"],
        "source_vendor_id": df["source_vendor_id"],
        "vendor_record_key": source + ":" + df["source_vendor_id"],
        "invoice_date_raw": df["invoice_date_raw"],
        "invoice_date": df["invoice_date_raw"].map(lambda v: parse_date(v, fmt)),
        "amount": df["amount_raw"].map(parse_amount),
        "currency": df["currency_raw"].map(lambda v: v.upper() if isinstance(v, str) else None),
    })
