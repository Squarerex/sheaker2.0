# storefront/views_account.py
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.forms import AddressForm
from accounts.models import Address

SESSION_SHIP_ADDR_KEY = "checkout_shipping_address_id"


@login_required
def addresses_list(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "storefront/account/addresses_list.html",
        {
            "addresses": request.user.addresses.all(),
        },
    )


@login_required
def address_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = AddressForm(request.POST)
        if form.is_valid():
            addr = form.save(commit=False)
            addr.user = request.user
            if addr.is_default:
                request.user.addresses.update(is_default=False)
            addr.save()
            messages.success(request, "Address saved.")
            return redirect("storefront:addresses_list")
    else:
        form = AddressForm()
    return render(request, "storefront/account/address_form.html", {"form": form})


@login_required
def address_edit(request: HttpRequest, pk: int) -> HttpResponse:
    addr = get_object_or_404(Address, pk=pk, user=request.user)
    if request.method == "POST":
        form = AddressForm(request.POST, instance=addr)
        if form.is_valid():
            addr = form.save()
            if addr.is_default:
                request.user.addresses.exclude(pk=addr.pk).update(is_default=False)
            messages.success(request, "Address updated.")
            return redirect("storefront:addresses_list")
    else:
        form = AddressForm(instance=addr)
    return render(request, "storefront/account/address_form.html", {"form": form})


@login_required
def address_delete(request: HttpRequest, pk: int) -> HttpResponse:
    addr = get_object_or_404(Address, pk=pk, user=request.user)
    if request.method == "POST":
        addr.delete()
        messages.info(request, "Address removed.")
        return redirect("storefront:addresses_list")
    return render(request, "storefront/account/address_confirm_delete.html", {"address": addr})


@login_required
def choose_shipping_address(request: HttpRequest, pk: int) -> HttpResponse:
    addr = get_object_or_404(Address, pk=pk, user=request.user)
    request.session[SESSION_SHIP_ADDR_KEY] = addr.pk
    messages.success(request, "Shipping address selected.")
    return HttpResponseRedirect(reverse("storefront:cart_review"))