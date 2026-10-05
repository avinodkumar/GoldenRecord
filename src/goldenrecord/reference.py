"""Reference data: countries, city aliases and legal-form tokens."""
from __future__ import annotations

# ISO2 -> (full name, ISO3, phone country code, currency)
COUNTRIES = {
    "IN": ("India", "IND", "91", "INR"),
    "US": ("United States", "USA", "1", "USD"),
    "GB": ("United Kingdom", "GBR", "44", "GBP"),
    "DE": ("Germany", "DEU", "49", "EUR"),
    "SG": ("Singapore", "SGP", "65", "SGD"),
}

VALID_CURRENCIES = sorted({c[3] for c in COUNTRIES.values()})

# canonical city -> aliases seen in source systems
CITIES = {
    "IN": [("Bengaluru", ["Bangalore", "BLR"]), ("Mumbai", ["Bombay"]), ("Chennai", ["Madras"]),
           ("Kolkata", ["Calcutta"]), ("Gurugram", ["Gurgaon"]), ("Hyderabad", [])],
    "US": [("New York", ["NYC", "New York City"]), ("Chicago", []), ("San Francisco", ["SF"]), ("Dallas", [])],
    "GB": [("London", []), ("Manchester", [])],
    "DE": [("Munich", ["München", "Muenchen"]), ("Berlin", [])],
    "SG": [("Singapore", [])],
}

CITY_ALIASES = {
    alias.upper(): canonical
    for cities in CITIES.values()
    for canonical, aliases in cities
    for alias in [canonical, *aliases]
}

# Tokens dropped when normalizing vendor names for matching.
LEGAL_TOKENS = {
    "PVT", "PRIVATE", "LTD", "LIMITED", "INC", "INCORPORATED", "CORP", "CORPORATION",
    "LLC", "PLC", "GMBH", "AG", "PTE", "CO", "COMPANY",
}

# Common abbreviations expanded before matching.
NAME_ABBREVIATIONS = {
    "TECH": "TECHNOLOGIES", "ENGG": "ENGINEERING", "SVCS": "SERVICES", "PHARMACEUTICALS": "PHARMA",
    "INTL": "INTERNATIONAL", "MFG": "MANUFACTURING", "DIST": "DISTRIBUTORS", "COMMS": "TELECOM",
}


def country_to_iso2(value: str | None) -> str | None:
    """Map ISO2, ISO3 or a full country name to ISO2; None when unknown."""
    if not value:
        return None
    v = value.strip().upper()
    for iso2, (name, iso3, _, _) in COUNTRIES.items():
        if v in (iso2, iso3, name.upper()):
            return iso2
    return None
