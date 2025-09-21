# core/context_processors.py
from typing import Any, Dict

from django.conf import settings

# Optional imports guarded to avoid startup failures if modules move
try:
    from orders.cart import Cart
except Exception:  # pragma: no cover
    Cart = None  # type: ignore

try:
    from core.currency import detect_user_currency  # resolves in your tree
except Exception:  # pragma: no cover

    def detect_user_currency(address_country: str | None = None) -> str:
        # Safe fallback if your currency util isn't importable during setup
        return "GBP"


def currency_context(request) -> Dict[str, Any]:
    """
    Provides currencies to every template.
    If you capture a country code in session (e.g. via geo-IP or chosen address),
    set request.session["user_country_code"] = "NG"/"GB"/...
    """
    addr_country = request.session.get("user_country_code")  # optional
    user_currency = detect_user_currency(address_country=addr_country)
    return {
        "user_currency": user_currency,  # for PLP/PDP local display
        "base_currency": getattr(settings, "BASE_CURRENCY", "GBP"),
        "checkout_currency": getattr(settings, "CHECKOUT_CURRENCY", "GBP"),
    }


def cart_context(request) -> Dict[str, Any]:
    """
    Make a Cart instance available in all templates as {{ cart }}.
    Also keep a scalar count in session (optional convenience).
    """
    cart = Cart(request) if Cart else None  # type: ignore
    try:
        request.session["cart_count"] = int(cart.total_qty) if cart else 0
    except Exception:
        request.session["cart_count"] = request.session.get("cart_count", 0)
    request.session.modified = True
    return {"cart": cart}


def storefront_currency_context(request) -> Dict[str, Any]:
    """
    Light-weight currency hints for the storefront selector.
    """
    supported = ["GBP", "USD", "EUR", "NGN"]
    user_ccy = (
        request.session.get("manual_currency") or request.session.get("user_currency") or "GBP"
    )
    location = request.session.get("location_data", {})  # {"country_code": "GB", ...} if you set it
    return {
        "SUPPORTED_CURRENCIES": supported,
        "USER_CURRENCY": user_ccy,
        "LOCATION_DATA": location,
    }


def storefront_globals(request) -> Dict[str, Any]:
    """
    Sitewide simple values: site_name and (optionally) header_categories.
    Uses a guarded import so startup doesn't fail if Category moves.
    """
    site_name = getattr(settings, "SITE_NAME", "Sheaker")
    header_categories: list[Any] = []
    try:
        from catalog.models import Category  # local import to avoid circulars

        header_categories = list(Category.objects.filter(is_active=True).order_by("name")[:8])
    except Exception:
        # If Category model isn't available yet, just leave the list empty.
        header_categories = []

    return {
        "site_name": site_name,
        "header_categories": header_categories,
    }
