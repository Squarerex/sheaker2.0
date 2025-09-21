# core/currency.py
from __future__ import annotations

import json
import urllib.request
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional

from django.conf import settings
from django.core.cache import cache

# Minimal country->currency map (extend as needed)
COUNTRY_TO_CURRENCY = {
    "NG": "NGN",
    "GB": "GBP",
    "US": "USD",
    "CA": "CAD",
    "EU": "EUR",
    "FR": "EUR",
    "DE": "EUR",
    "IE": "EUR",
    "NL": "EUR",
    "ES": "EUR",
    "IT": "EUR",
    "KE": "KES",
    "GH": "GHS",
    "ZA": "ZAR",
}


def detect_user_currency(*, address_country: Optional[str] = None) -> str:
    """
    Decide what currency to display on storefront/PDP/PLP.
    If you store user's country in session or have a chosen shipping address,
    pass its ISO-2 code as `address_country`.
    """
    if address_country:
        return COUNTRY_TO_CURRENCY.get(
            address_country.upper(), settings.DEFAULT_USER_DISPLAY_CURRENCY
        )
    return getattr(settings, "DEFAULT_USER_DISPLAY_CURRENCY", "GBP")


def _fetch_rates_exchangerate_host(base: str) -> dict[str, float]:
    url = f"https://api.exchangerate.host/latest?base={base}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("rates", {}) or {}


def load_rates(base: str) -> dict[str, float]:
    """
    Returns mapping like {"USD": 1.24, "NGN": 1600.0, ...} for 1 base unit.
    Cached for FX_CACHE_SECONDS.
    """
    key = f"fx_rates_{base}"
    cached = cache.get(key)
    if cached:
        return cached
    rates = _fetch_rates_exchangerate_host(base)
    cache.set(key, rates, int(getattr(settings, "FX_CACHE_SECONDS", 21600)))
    return rates


def convert(
    amount: Decimal, from_currency: str, to_currency: str, rates: Optional[dict[str, float]] = None
) -> Decimal:
    """
    Convert `amount` from from_currency -> to_currency.
    If rate missing, returns amount rounded to 2dp.
    """
    amount = Decimal(amount)
    if from_currency.upper() == to_currency.upper():
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    try:
        rates = rates or load_rates(from_currency.upper())
        fx = rates.get(to_currency.upper())
        if not fx:
            return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        out = amount * Decimal(str(fx))
        return out.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def fmt(amount: Decimal, currency: str) -> str:
    """Simple formatting with symbols."""
    symbols = {
        "GBP": "£",
        "NGN": "₦",
        "USD": "$",
        "EUR": "€",
        "CAD": "C$",
        "KES": "KSh",
        "GHS": "₵",
        "ZAR": "R",
    }
    sym = symbols.get(currency.upper(), currency.upper() + " ")
    return f"{sym}{Decimal(amount):,.2f}"
