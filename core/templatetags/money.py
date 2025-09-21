# core/templatetags/money.py
from __future__ import annotations

from decimal import Decimal

from django import template

from core.currency import convert, fmt

register = template.Library()


@register.simple_tag
def money_gbp(amount: Decimal):
    """Format a GBP amount (authoritative)."""
    return fmt(Decimal(amount), "GBP")


@register.simple_tag
def money_local(amount_gbp: Decimal, user_currency: str):
    """Render GBP amount converted to the user's local currency."""
    local_amt = convert(Decimal(amount_gbp), "GBP", user_currency)
    return fmt(local_amt, user_currency)
