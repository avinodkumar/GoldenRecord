"""Project-wide settings shared by the local pipeline and the Fabric notebooks."""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("GOLDENRECORD_DATA_DIR", PROJECT_ROOT / "data"))
CONFIG_DIR = Path(os.environ.get("GOLDENRECORD_CONFIG_DIR", PROJECT_ROOT / "config"))
# Root of the local lakehouse (OneLake stand-in): Tables/ holds Delta tables, Files/ holds landing data.
LAKEHOUSE_ROOT = Path(os.environ.get("LAKEHOUSE_ROOT", DATA_DIR / "lakehouse"))

RAW_DIR = DATA_DIR / "raw"
TRUTH_DIR = DATA_DIR / "truth"
BRONZE_DIR = DATA_DIR / "bronze"
SILVER_DIR = DATA_DIR / "silver"
GOLD_DIR = DATA_DIR / "gold"
LABELS_DIR = DATA_DIR / "labels"
REPORTS_DIR = DATA_DIR / "reports"

SOURCES = ("ERP_A", "ERP_B", "ERP_C")

# Lower number wins during survivorship. ERP_C is the best-maintained system in our scenario.
SOURCE_PRIORITY = {"ERP_C": 1, "ERP_A": 2, "ERP_B": 3}

# Confidence bands for match decisions.
HIGH_BAND = 0.90    # auto-merge into Gold
MEDIUM_BAND = 0.70  # human review queue; below this is "no match"

# AI review of the grey zone (ADR 0002)
GREY_ZONE = (0.50, 0.90)       # deterministic scores the AI is asked about
AI_PROMOTE_MIN_SCORE = 0.80    # the AI can raise a pair to HIGH only at or above this score
AI_MIN_CONFIDENCE = 0.80

# Anomaly check: an invoice is flagged when it exceeds this multiple of the vendor's median amount.
ANOMALY_MULTIPLIER = 20.0
ANOMALY_MIN_HISTORY = 3

# Static demo FX rates to USD (illustrative, not market data).
FX_TO_USD = {"USD": 1.0, "INR": 0.012, "GBP": 1.27, "EUR": 1.08, "SGD": 0.74}

TAX_ID_PATTERN = r"^[A-Z]{2}[A-Z0-9]{10}$"
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
