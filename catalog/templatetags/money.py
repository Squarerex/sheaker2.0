from decimal import ROUND_HALF_UP, Decimal

from django import template

register = template.Library()

_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "NGN": "₦",
}


@register.filter
def money(value, currency=""):
    """
    Usage: {{ 123.456|money:"USD" }} → $123.46
           {{ price|money:variant.currency }}
    """
    if value is None:
        return ""
    try:
        amt = (Decimal(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return str(value)
    sym = _SYMBOLS.get(currency or "", "")
    if sym:
        return f"{sym}{amt}"
    if currency:
        return f"{currency} {amt}"
    return f"{amt}"
