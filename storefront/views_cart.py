# storefront/views_cart.py
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from orders.cart import Cart
from orders.services.validation import sanitize_cart


def cart_detail(request):
    cart = Cart(request)
    return render(
        request,
        "storefront/cart.html",
        {
            "cart": cart,
            "cart_currency": "GBP",
        },
    )


@require_POST
def cart_add(request):
    variant_id = request.POST.get("variant_id")
    qty = request.POST.get("qty", "1")
    if not variant_id:
        return HttpResponseBadRequest("variant_id required")
    cart = Cart(request)
    cart.add(int(variant_id), int(qty))
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
    cart.update(int(variant_id), int(qty))
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return HttpResponse(status=204)
    return redirect(reverse("storefront:cart_detail"))


@require_POST
def cart_remove(request):
    variant_id = request.POST.get("variant_id")
    if not variant_id:
        return HttpResponseBadRequest("variant_id required")
    cart = Cart(request)
    cart.remove(int(variant_id))
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return HttpResponse(status=204)
    return redirect(reverse("storefront:cart_detail"))


def checkout_start(request):
    cart = Cart(request)
    removed = sanitize_cart(cart, destination_country_code="GB")
    if removed:
        from django.contrib import messages

        names = ", ".join(
            {
                getattr(x["variant"], "product", None)
                and getattr(x["variant"].product, "title", None)
                or f"#{x['variant'].id}"
                for x in removed
            }
        )
        messages.warning(request, f"Some items were removed before checkout: {names}")
    return redirect("storefront:cart_detail")


def cart_mini(request):
    from django.template.loader import render_to_string

    cart = Cart(request)
    html = render_to_string(
        "storefront/_partials_minicart.html",
        {
            "cart": cart,
            "cart_currency": "GBP",
        },
        request=request,
    )
    return JsonResponse({"html": html, "count": cart.total_qty})
