# orders/services/tax.py
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

INCLUSIVE_PRICING = True  # if True, product prices already include tax
FLAT_TAX_RATE = Decimal("0.075")  # 7.5% VAT example


def compute_tax(subtotal: Decimal) -> tuple[Decimal, Decimal]:
    """Return (tax_amount, total)"""
    if INCLUSIVE_PRICING:
        tax_amount = (subtotal - (subtotal / (Decimal("1.0") + FLAT_TAX_RATE))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        total = subtotal
    else:
        tax_amount = (subtotal * FLAT_TAX_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total = (subtotal + tax_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return tax_amount, total
