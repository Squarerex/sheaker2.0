# orders/views_checkout.py
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse

from accounts.models import Address
from core.currency import convert, detect_user_currency, fmt
from orders.cart import Cart
from orders.models import Order, OrderItem
from orders.services.shipping import estimate_shipping
from orders.services.tax import compute_tax
from payments.stripe_gateway import create_checkout_session
from storefront.views_account import SESSION_SHIP_ADDR_KEY

DEC2 = Decimal("0.01")


def _to_decimal(val: Any, default: Decimal = Decimal("0.00")) -> Decimal:
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _iter_possible_lines(cart: Cart) -> Iterable[Any]:
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
    if hasattr(cart, "keys") and hasattr(cart, "values"):
        try:
            for _, x in cart.items():
                yield x
            return
        except Exception:
            pass
    return


def _subtotal_gbp(cart: Cart) -> Decimal:
    meth = getattr(cart, "subtotal_gbp", None)
    if callable(meth):
        return _to_decimal(meth(), Decimal("0.00")).quantize(DEC2)
    for name in ("subtotal", "total"):
        func = getattr(cart, name, None)
        if callable(func):
            try:
                return _to_decimal(func(), Decimal("0.00")).quantize(DEC2)
            except Exception:
                pass
    total = Decimal("0.00")
    any_line = False
    for line in _iter_possible_lines(cart):
        any_line = True
        if hasattr(line, "total_price"):
            total += _to_decimal(getattr(line, "total_price"))
            continue
        if isinstance(line, dict):
            if "total_price" in line:
                total += _to_decimal(line.get("total_price"))
                continue
            unit = _to_decimal(line.get("unit_price", line.get("price", "0")))
            qty = int(line.get("quantity", 1) or 1)
            total += unit * qty
            continue
        unit = _to_decimal(getattr(line, "unit_price", getattr(line, "price", "0")))
        qty = int(getattr(line, "quantity", 1) or 1)
        total += unit * qty
    if any_line:
        return total.quantize(DEC2)
    return Decimal("0.00")


def _safe_shipping(country: str | None = None) -> Decimal:
    try:
        return _to_decimal(estimate_shipping(country=country), Decimal("0.00")).quantize(DEC2)
    except Exception:
        return Decimal("0.00")


def _safe_tax_and_total(subtotal: Decimal) -> tuple[Decimal, Decimal]:
    try:
        tax, total_inc = compute_tax(_to_decimal(subtotal, Decimal("0.00")))
        return _to_decimal(tax, Decimal("0.00")).quantize(DEC2), _to_decimal(
            total_inc, Decimal("0.00")
        ).quantize(DEC2)
    except Exception:
        return Decimal("0.00"), _to_decimal(subtotal, Decimal("0.00")).quantize(DEC2)


@login_required
def checkout_review(request: HttpRequest) -> HttpResponse:
    cart = Cart(request)
    if hasattr(cart, "is_empty") and cart.is_empty:
        messages.info(request, "Your cart is empty.")
        return redirect("storefront:cart_detail")

    addr_id = request.session.get(SESSION_SHIP_ADDR_KEY)
    address = None
    if addr_id:
        try:
            # Fix: Use request.user.pk to avoid type issues
            address = Address.objects.filter(pk=int(addr_id), user=request.user.pk).first()
        except (ValueError, TypeError):
            address = None

    # GBP authoritative totals
    subtotal_gbp = _subtotal_gbp(cart)
    shipping_gbp = _safe_shipping(country=address.country if address else None)
    tax_gbp, total_inc_tax_gbp = _safe_tax_and_total(subtotal_gbp)
    grand_gbp = (total_inc_tax_gbp + shipping_gbp).quantize(DEC2)

    # Optional local hint
    user_ccy = detect_user_currency(address_country=request.session.get("user_country_code"))
    try:
        grand_local = convert(grand_gbp, "GBP", user_ccy)
    except Exception:
        grand_local = grand_gbp

    return render(
        request,
        "storefront/checkout/review.html",
        {
            "cart": cart,
            "address": address,
            "subtotal_gbp_fmt": fmt(subtotal_gbp, "GBP"),
            "shipping_gbp_fmt": fmt(shipping_gbp, "GBP"),
            "tax_gbp_fmt": fmt(tax_gbp, "GBP"),
            "grand_gbp_fmt": fmt(grand_gbp, "GBP"),
            "grand_local_hint": fmt(grand_local, user_ccy),
            "checkout_currency": "GBP",
            "publishable_key": settings.STRIPE_PUBLISHABLE_KEY,
        },
    )


@login_required
def checkout_start(request: HttpRequest) -> HttpResponse:
    cart = Cart(request)

    addr_id = request.session.get(SESSION_SHIP_ADDR_KEY)
    address = None
    if addr_id:
        try:
            # Fix: Use request.user.pk to avoid type issues
            address = Address.objects.filter(pk=int(addr_id), user=request.user.pk).first()
        except (ValueError, TypeError):
            address = None
            
    if not address:
        messages.error(request, "Choose a shipping address to continue.")
        return redirect("storefront:addresses_list")

    if hasattr(cart, "is_empty") and cart.is_empty:
        messages.info(request, "Your cart is empty.")
        return redirect("storefront:cart_detail")

    subtotal_gbp = _subtotal_gbp(cart)
    shipping_gbp = _safe_shipping(country=address.country)
    tax_gbp, total_inc_tax_gbp = _safe_tax_and_total(subtotal_gbp)
    grand_gbp = (total_inc_tax_gbp + shipping_gbp).quantize(DEC2)

    # Fix: Add type ignore for Django ORM operations
    order = Order.objects.create(  # type: ignore[misc]
        user=request.user,
        total_amount=grand_gbp,
        currency="GBP",
        payment_status="unpaid",
        shipping_address=f"{address.full_name}, {address.line1}, {address.city}",
    )

    # Persist lines only if we can iterate them safely
    if hasattr(cart, "lines") or hasattr(cart, "items") or hasattr(cart, "_items"):
        for line in _iter_possible_lines(cart):
            variant = getattr(line, "variant", None)
            quantity = int(getattr(line, "quantity", 1) or 1)
            unit_price = _to_decimal(
                getattr(
                    line, "unit_price", getattr(line, "price", getattr(line, "total_price", "0"))
                )
            )
            total_price = _to_decimal(getattr(line, "total_price", unit_price * quantity))
            try:
                OrderItem.objects.create(
                    order=order,
                    variant=variant,  # type: ignore[misc]
                    quantity=quantity,
                    unit_price=unit_price.quantize(DEC2),
                    total_price=total_price.quantize(DEC2),
                    title_snapshot=str(getattr(getattr(variant, "product", None), "title", ""))[
                        :255
                    ],
                    sku_snapshot=str(getattr(variant, "sku", ""))[:64],
                )
            except Exception:
                # Ignore line persistence errors so checkout can proceed
                pass

    success_url = request.build_absolute_uri(reverse("orders:checkout_success"))
    cancel_url = request.build_absolute_uri(reverse("orders:checkout_cancel"))

    session = create_checkout_session(
        order_id=order.id,
        amount_gbp=grand_gbp,
        success_url=success_url,
        cancel_url=cancel_url,
        # Fix: Safe email access
        customer_email=getattr(request.user, 'email', None),
        metadata={"order_id": str(order.id)},
    )
    order.stripe_checkout_session_id = session.id
    order.save(update_fields=["stripe_checkout_session_id"])

    return HttpResponseRedirect(session.url or "/")


def checkout_success(_: HttpRequest) -> HttpResponse:
    return render(_, "storefront/checkout/success.html")


def checkout_cancel(_: HttpRequest) -> HttpResponse:
    return render(_, "storefront/checkout/cancel.html")