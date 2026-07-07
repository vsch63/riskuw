"""
backend/services/country_currency.py
──────────────────────────────────────
Single source of truth mapping operating countries to default currency
and integration providers. Used by:
  - routers/tenants.py     (auto-derive currency on country change)
  - routers/system.py      (resolve currency for display)
  - routers/integrations.py (resolve default country for verification calls)
"""

COUNTRY_CURRENCY_MAP = {
    "IN": {"currency_code": "INR", "currency_symbol": "₹", "currency_name": "Indian Rupee",      "country_name": "India",          "flag": "🇮🇳"},
    "AE": {"currency_code": "AED", "currency_symbol": "د.إ", "currency_name": "UAE Dirham",       "country_name": "United Arab Emirates", "flag": "🇦🇪"},
    "SG": {"currency_code": "SGD", "currency_symbol": "S$", "currency_name": "Singapore Dollar",   "country_name": "Singapore",      "flag": "🇸🇬"},
    "GB": {"currency_code": "GBP", "currency_symbol": "£", "currency_name": "British Pound",       "country_name": "United Kingdom", "flag": "🇬🇧"},
    "US": {"currency_code": "USD", "currency_symbol": "$", "currency_name": "US Dollar",           "country_name": "United States",  "flag": "🇺🇸"},
}

DEFAULT_COUNTRY = "IN"


def currency_for_country(country_code: str) -> dict:
    """Returns currency_code/symbol/name for a given country, fallback to India."""
    return COUNTRY_CURRENCY_MAP.get(country_code, COUNTRY_CURRENCY_MAP[DEFAULT_COUNTRY])


def country_meta(country_code: str) -> dict:
    return COUNTRY_CURRENCY_MAP.get(country_code, {"country_name": country_code, "flag": "🌍"})


def list_countries() -> list[dict]:
    return [
        {"code": k, **v} for k, v in COUNTRY_CURRENCY_MAP.items()
    ]
