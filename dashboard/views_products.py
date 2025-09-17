from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from catalog.models import Category, Product, Subcategory

from .authz import role_required
from .forms_products import ProductForm, ProductMediaFormSet, VariantFormSet


def _get_page_obj(queryset, request: HttpRequest):
    """Paginate with ?page and optional ?page_size (defaults to 25, min 5, max 100)."""
    try:
        page_size = int(request.GET.get("page_size", 25))
    except (TypeError, ValueError):
        page_size = 25
    page_size = max(5, min(page_size, 100))

    paginator = Paginator(queryset, page_size)
    page = request.GET.get("page", 1)
    try:
        return paginator.page(page)
    except PageNotAnInteger:
        return paginator.page(1)
    except EmptyPage:
        return paginator.page(paginator.num_pages)


@role_required(["admin", "editor", "marketer"])
def product_list(request: HttpRequest) -> HttpResponse:
    """
    Search & filters:
      - q: title or variants.sku (icontains)
      - brand: exact (case-insensitive)
      - category: id or slug
      - subcategory: id or slug
      - active: 'true' | 'false'
      - page / page_size: pagination
    """
    qs = (
        Product.objects.all()
        .select_related("category", "subcategory")
        .prefetch_related("variants")
    )

    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(variants__sku__icontains=q))

    brand = (request.GET.get("brand") or "").strip()
    if brand:
        qs = qs.filter(brand__iexact=brand)

    category = (request.GET.get("category") or "").strip()
    if category:
        if category.isdigit():
            qs = qs.filter(category_id=int(category))
        else:
            qs = qs.filter(category__slug=category)

    subcategory = (request.GET.get("subcategory") or "").strip()
    if subcategory:
        if subcategory.isdigit():
            qs = qs.filter(subcategory_id=int(subcategory))
        else:
            qs = qs.filter(subcategory__slug=subcategory)

    active = (request.GET.get("active") or "").strip().lower()
    if active in {"true", "false"}:
        qs = qs.filter(is_active=(active == "true"))

    qs = qs.order_by("-created_at").distinct()

    page_obj = _get_page_obj(qs, request)

    ctx: dict[str, Any] = {
        "products": page_obj,  # backward compat if templates used "products"
        "page_obj": page_obj,
        "paginator": page_obj.paginator,
        # echo filters for template inputs / pager links
        "q": q,
        "brand": brand,
        "category": category,
        "subcategory": subcategory,
        "active": active,
        # optional helpers if your template wants dropdowns
        "all_categories": Category.objects.filter(is_active=True).order_by("name"),
        "all_subcategories": Subcategory.objects.filter(is_active=True).order_by(
            "category__name", "name"
        ),
    }
    return render(request, "dashboard/products/product_list.html", ctx)


@role_required(["admin", "editor"])
@transaction.atomic
def product_create(request: HttpRequest) -> HttpResponse:
    product = Product()
    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES, instance=product)
        v_formset = VariantFormSet(request.POST, instance=product, prefix="v")
        m_formset = ProductMediaFormSet(
            request.POST, request.FILES, instance=product, prefix="m"
        )
        if form.is_valid() and v_formset.is_valid() and m_formset.is_valid():
            form.save()
            v_formset.save()
            m_formset.save()
            messages.success(request, "Product created.")
            return redirect("dashboard:product_list")
    else:
        form = ProductForm(instance=product)
        v_formset = VariantFormSet(instance=product, prefix="v")
        m_formset = ProductMediaFormSet(instance=product, prefix="m")

    return render(
        request,
        "dashboard/products/product_form.html",
        {
            "mode": "create",
            "form": form,
            "v_formset": v_formset,
            "m_formset": m_formset,
        },
    )


@role_required(["admin", "editor"])
@transaction.atomic
def product_edit(request: HttpRequest, pk: int) -> HttpResponse:
    product = get_object_or_404(Product, pk=pk)
    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES, instance=product)
        v_formset = VariantFormSet(request.POST, instance=product, prefix="v")
        m_formset = ProductMediaFormSet(
            request.POST, request.FILES, instance=product, prefix="m"
        )
        if form.is_valid() and v_formset.is_valid() and m_formset.is_valid():
            form.save()
            v_formset.save()
            m_formset.save()
            messages.success(request, "Product saved.")
            return redirect("dashboard:product_list")
    else:
        form = ProductForm(instance=product)
        v_formset = VariantFormSet(instance=product, prefix="v")
        m_formset = ProductMediaFormSet(instance=product, prefix="m")

    return render(
        request,
        "dashboard/products/product_form.html",
        {"mode": "edit", "form": form, "v_formset": v_formset, "m_formset": m_formset},
    )
