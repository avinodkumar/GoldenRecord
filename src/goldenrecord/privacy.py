"""PII protection at ingestion: raw personal data never lands in Bronze, Silver or Gold.

At ingestion every PII field is split three ways:
  * a keyed token (HMAC-SHA256) used for matching: equal values give equal tokens, the value is not recoverable
  * a format-preserving masked value for display and format checks ("a***@apex.co.in", "+91******3210")
  * the raw value, written only to the restricted pii_vault table (OneLake security: pii-custodian role)

The key comes from PII_TOKEN_KEY (Azure Key Vault in Fabric). The dev default is for local runs only.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re

import pandas as pd

log = logging.getLogger(__name__)
_DEV_KEY = "goldenrecord-dev-only-key"


def _key() -> bytes:
    key = os.environ.get("PII_TOKEN_KEY")
    if not key:
        key = _DEV_KEY
    return key.encode()


def tokenize(value: str | None, kind: str) -> str | None:
    if value is None:
        return None
    digest = hmac.new(_key(), f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()
    return f"tok_{digest[:24]}"


def canonical_phone(value) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    digits = re.sub(r"\D", "", value)
    if digits.startswith("00"):
        digits = digits[2:]
    return f"+{digits}" if len(digits) >= 8 else None


def canonical_email(value) -> str | None:
    return value.strip().lower() if isinstance(value, str) and value.strip() else None


def canonical_bank(value) -> str | None:
    if not isinstance(value, str):
        return None
    digits = re.sub(r"\D", "", value)
    return digits or None


def mask_phone(phone: str | None) -> str | None:
    return None if not phone else phone[:3] + "*" * max(len(phone) - 7, 0) + phone[-4:]


def mask_email(email: str | None) -> str | None:
    """Keeps the structure (and so the format rule R04) but hides the local part."""
    if not email:
        return None
    if "@" not in email:
        return email[:1] + "***"
    local, domain = email.rsplit("@", 1)
    return f"{local[:1]}***@{domain}"


def mask_bank(bank: str | None) -> str | None:
    return None if not bank else "****" + bank[-4:]


# Source column names that hold personal data, per ERP.
PII_COLUMNS = {
    "ERP_A": {"phone": "TELF1", "email": "SMTP_ADDR", "bank": "BANKN"},
    "ERP_B": {"phone": "PHONE", "email": "EMAIL", "bank": "BANK_ACCOUNT_NUM"},
    "ERP_C": {"phone": "PrimaryPhone", "email": "PrimaryEmail", "bank": "BankAccountNumber"},
}
ID_COLUMN = {"ERP_A": "LIFNR", "ERP_B": "VENDOR_ID", "ERP_C": "VendorAccountNumber"}
_CANONICAL = {"phone": canonical_phone, "email": canonical_email, "bank": canonical_bank}
_MASK = {"phone": mask_phone, "email": mask_email, "bank": mask_bank}


def protect_vendor_pii(raw: pd.DataFrame, source: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (protected extract, vault rows). The protected extract keeps the source schema with masked
    values in the PII columns plus pii_<kind>_token columns; the vault holds the raw values."""
    out = raw.copy()
    vault = []
    keys = source + ":" + raw[ID_COLUMN[source]].astype(str)
    for kind, col in PII_COLUMNS[source].items():
        canonical = raw[col].map(_CANONICAL[kind])
        out[f"pii_{kind}_token"] = canonical.map(lambda v, k=kind: tokenize(v, k))
        # Invalid emails keep their (masked) shape so the format rule can still catch them.
        masked_source = canonical if kind != "email" else raw[col].map(lambda v: v.strip() if isinstance(v, str) else v)
        out[col] = masked_source.map(_MASK[kind]).fillna("")
        vault.append(pd.DataFrame({"record_key": keys, "field": kind, "raw_value": raw[col]}))
    return out, pd.concat(vault, ignore_index=True)


def contains_raw_pii(df: pd.DataFrame, vault: pd.DataFrame) -> list[str]:
    """Columns of df that contain any raw PII value from the vault (used by tests and the audit)."""
    secrets = {v for v in vault["raw_value"] if isinstance(v, str) and len(v) >= 6}
    return [c for c in df.columns if df[c].dtype == object and df[c].isin(secrets).any()]
