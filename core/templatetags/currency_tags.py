from django import template

register = template.Library()

_FLAG = {
    "GBP": "gb",
    "NGN": "ng",
    "USD": "us",
    "EUR": "eu",
    "CAD": "ca",
    "KES": "ke",
    "GHS": "gh",
    "ZAR": "za",
}


@register.filter
def currency_flag(ccy_code: str) -> str:
    """Return flag-icons country code for a currency code."""
    if not ccy_code:
        return "un"  # unknown
    return _FLAG.get(str(ccy_code).upper(), "un")
