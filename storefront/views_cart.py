# storefront/views_cart.py
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.currency import convert, detect_user_currency, fmt
from orders.cart import Cart
from orders.services.shipping import estimate_shipping
from orders.services.tax import compute_tax
from orders.services.validation import sanitize_cart

DEC2 = Decimal("0.01")


def _to_decimal(val: Any, default: Decimal = Decimal("0.00")) -> Decimal:
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _iter_possible_lines(cart: Cart) -> Iterable[Any]:
    """
    Try multiple conventions to retrieve cart line items.
    Yields objects or dicts that expose either:
      - total_price, or
      - unit_price/price and quantity
    """
    lines = getattr(cart, "lines", None)
    if callable(lines):
        try:
            for x in lines():
                yield x
            return
        except Exception:
            pass

    items = getattr(cart, "items", None)
    if items:
        try:
            for x in items:
                yield x
            return
        except Exception:
            pass

    _items = getattr(cart, "_items", None)
    if _items:
        try:
            for x in _items:
                yield x
            return
        except Exception:
            pass

    if hasattr(cart, "items") and callable(getattr(cart, "items")):
        try:
            for _, x in cart.items():  # type: ignore[attr-defined]
                yield x
            return
        except Exception:
            pass

    return


def _subtotal_gbp(cart: Cart) -> Decimal:
    """
    Best-effort subtotal in GBP, tolerant of many Cart implementations.
    Never raises; falls back to 0.00 GBP.
    """
    # Preferred explicit methods
    m = getattr(cart, "subtotal_gbp", None)
    if callable(m):
        return _to_decimal(m(), Decimal("0.00")).quantize(DEC2)

    for name in ("subtotal", "total"):
        fn = getattr(cart, name, None)
        if callable(fn):
            try:
                return _to_decimal(fn(), Decimal("0.00")).quantize(DEC2)
            except Exception:
                pass

    # Sum discovered lines
    running = Decimal("0.00")
    any_line = False
    for line in _iter_possible_lines(cart):
        any_line = True
        if hasattr(line, "total_price"):
            running += _to_decimal(getattr(line, "total_price"))
            continue
        if isinstance(line, dict):
            if "total_price" in line:
                running += _to_decimal(line.get("total_price"))
                continue
            unit = _to_decimal(line.get("unit_price", line.get("price", "0")))
            qty = int(line.get("quantity", 1) or 1)
            running += unit * qty
            continue
        unit = _to_decimal(getattr(line, "unit_price", getattr(line, "price", "0")))
        qty = int(getattr(line, "quantity", 1) or 1)
        running += unit * qty

    if any_line:
        return running.quantize(DEC2)

    return Decimal("0.00")


def _safe_shipping(country: str | None = None) -> Decimal:
    try:
        val = estimate_shipping(country=country)
        return _to_decimal(val, Decimal("0.00")).quantize(DEC2)
    except Exception:
        return Decimal("0.00")


def _safe_tax_and_total(subtotal: Decimal) -> tuple[Decimal, Decimal]:
    """
    compute_tax expected to return (tax, total_inclusive).
    Guard & normalize.
    """
    try:
        tax, total_inc = compute_tax(_to_decimal(subtotal, Decimal("0.00")))
        tax = _to_decimal(tax, Decimal("0.00")).quantize(DEC2)
        total_inc = _to_decimal(total_inc, Decimal("0.00")).quantize(DEC2)
        return tax, total_inc
    except Exception:
        return Decimal("0.00"), _to_decimal(subtotal, Decimal("0.00")).quantize(DEC2)


def cart_detail(request):
    cart = Cart(request)

    # GBP-authoritative math
    subtotal_gbp = _subtotal_gbp(cart)
    shipping_gbp = _safe_shipping()
    tax_gbp, total_inc_tax_gbp = _safe_tax_and_total(subtotal_gbp)
    grand_gbp = (total_inc_tax_gbp + shipping_gbp).quantize(DEC2)

    # Expose variables your template expects:
    # - cart_currency (used by {{ ...|money:cart_currency }})
    # - cart.total_price (so {{ cart.total_price }} exists)
    cart_currency = "GBP"
    try:
        setattr(cart, "total_price", grand_gbp)
    except Exception:
        # If Cart is implemented as a proxy without attribute setting, ignore
        pass

    # Optional UI hint in user-local currency (display only)
    user_ccy = detect_user_currency(address_country=request.session.get("user_country_code"))
    try:
        grand_local = convert(grand_gbp, "GBP", user_ccy)
    except Exception:
        grand_local = grand_gbp

    return render(
        request,
        "storefront/cart.html",  # if your template path is different, adjust here
        {
            "cart": cart,
            "cart_currency": cart_currency,  # ✅ fixes VariableDoesNotExist
            "subtotal_gbp": subtotal_gbp,
            "shipping_gbp": shipping_gbp,
            "tax_gbp": tax_gbp,
            "grand_gbp": grand_gbp,
            "subtotal_gbp_fmt": fmt(subtotal_gbp, "GBP"),
            "shipping_gbp_fmt": fmt(shipping_gbp, "GBP"),
            "tax_gbp_fmt": fmt(tax_gbp, "GBP"),
            "grand_gbp_fmt": fmt(grand_gbp, "GBP"),
            "grand_local_hint": fmt(grand_local, user_ccy),
        },
    )


@require_POST
def cart_add(request):
    variant_id = request.POST.get("variant_id")
    qty = request.POST.get("qty", "1")
    if not variant_id:
        return HttpResponseBadRequest("variant_id required")

    cart = Cart(request)
    try:
        cart.add(int(variant_id), int(qty))
    except Exception:
        pass

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return HttpResponse(status=204)
    return redirect(request.META.get("HTTP_REFERER", reverse("storefront:cart_detail")))


@require_POST
def cart_update(request):
    variant_id = request.POST.get("variant_id")
    qty = request.POST.get("qty")
    if not (variant_id and qty):
        return HttpResponseBadRequest("variant_id and qty required")

    cart = Cart(request)
    try:
        cart.update(int(variant_id), int(qty))
    except Exception:
        pass

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return HttpResponse(status=204)
    return redirect(reverse("storefront:cart_detail"))


@require_POST
def cart_remove(request):
    variant_id = request.POST.get("variant_id")
    if not variant_id:
        return HttpResponseBadRequest("variant_id required")

    cart = Cart(request)
    try:
        cart.remove(int(variant_id))
    except Exception:
        pass

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return HttpResponse(status=204)
    return redirect(reverse("storefront:cart_detail"))


def checkout_start(request):
    cart = Cart(request)
    try:
        removed = sanitize_cart(cart, destination_country_code="GB")
    except Exception:
        removed = []

    if removed:
        from django.contrib import messages

        names = ", ".join(
            {
                (
                    getattr(x["variant"], "product", None)
                    and getattr(x["variant"].product, "title", None)
                )
                or f"#{getattr(x.get('variant'), 'id', 'unknown')}"
                for x in removed
                if isinstance(x, dict)
            }
        )
        messages.warning(request, f"Some items were removed before checkout: {names}")
    return redirect("storefront:cart_detail")


def cart_mini(request):
    cart = Cart(request)
    html = render_to_string(
        "storefront/_partials_minicart.html",
        {"cart": cart, "cart_currency": "GBP"},
        request=request,
    )
    return JsonResponse({"html": html, "count": getattr(cart, "total_qty", 0)})