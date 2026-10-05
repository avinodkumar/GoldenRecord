from datetime import date

from goldenrecord.reference import country_to_iso2
from goldenrecord.standardize import clean_city, clean_phone, clean_tax_id, normalize_name, parse_amount, parse_date


def test_normalize_name_drops_legal_forms_and_punctuation():
    assert normalize_name("Apex Logistics Pvt. Ltd.") == "APEX LOGISTICS"
    assert normalize_name("APEX LOGISTICS PRIVATE LIMITED") == "APEX LOGISTICS"
    assert normalize_name("Helix Tech L.L.C.") == "HELIX TECHNOLOGIES"


def test_country_mapping_accepts_iso2_iso3_and_names():
    assert country_to_iso2("IN") == "IN"
    assert country_to_iso2("IND") == "IN"
    assert country_to_iso2("United Kingdom") == "GB"
    assert country_to_iso2("Unknown") is None


def test_tax_phone_and_city_cleaning():
    assert clean_tax_id("in 4f7k-2P9Q1Z") == "IN4F7K2P9Q1Z"
    assert clean_tax_id("") is None
    assert clean_phone("0091 98765 43210") == "+919876543210"
    assert clean_phone("(91) 987-654-3210") == "+919876543210"
    assert clean_city("Bangalore") == "Bengaluru"
    assert clean_city("muenchen") == "Munich"


def test_dates_and_amounts_per_source_format():
    assert parse_date("20250314", "%Y%m%d") == date(2025, 3, 14)
    assert parse_date("14-MAR-2025", "%d-%b-%Y") == date(2025, 3, 14)
    assert parse_date("31-FEB-2025", "%d-%b-%Y") is None
    assert parse_amount("1,234.50") == 1234.5
    assert parse_amount("") is None
