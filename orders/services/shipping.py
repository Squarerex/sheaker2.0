# orders/services/shipping.py
from __future__ import annotations

from decimal import Decimal

FLAT_RATE = Decimal("2500.00")  # NGN; adjust per country/weight later


def estimate_shipping(*, country: str | None = None) -> Decimal:
    # Placeholder; expand with zones/weights or supplier-direct logic later
    return FLAT_RATE
