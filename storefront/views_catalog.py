# storefront/views_catalog.py
from __future__ import annotations

from decimal import Decimal

from django.core.paginator import Paginator
from django.db.models import Min, Prefetch
from django.shortcuts import get_object_or_404, render

from catalog.models import Inventory, Product, Variant

try:
    from catalog.models import Category  # if your project has Category
except Exception:
    Category = None

from providers.models import SupplierProduct

try:
    from reviews.models import Review
except Exception:
    Review = None


# ---------- helpers ----------
def _base_product_qs():
    return (
        Product.objects.filter(is_active=True)
        .select_related("category")
        .prefetch_related(
            Prefetch("variants", queryset=Variant.objects.filter(is_active=True).order_by("id")),
            "media",
        )
    )


def _sorted_paginated_products(request, base_qs, per_page: int = 24):
    SORT_OPTIONS = {
        "new": ("-id", "Newest"),
        "price_asc": ("min_price", "Price: Low → High"),
        "price_desc": ("-min_price", "Price: High → Low"),
        "title": ("title", "Title A–Z"),
    }
    DEFAULT_SORT = "new"

    qs = base_qs.annotate(min_price=Min("variants__price_base"))
    sort_key = request.GET.get("sort", DEFAULT_SORT)
    sort_field = SORT_OPTIONS.get(sort_key, SORT_OPTIONS[DEFAULT_SORT])[0]
    qs = qs.order_by(sort_field, "id")
    paginator = Paginator(qs, per_page)
    page_obj = paginator.get_page(request.GET.get("page") or 1)
    return page_obj, sort_key, SORT_OPTIONS


def _breadcrumb3_home_only():
    # Always (label, urlname, arg) triplets for JSON-LD
    return [("Home", "storefront:home", None)]


# ---------- Public pages ----------
def home(request):
    """
    Curated rails and 'See all' views via ?view=recommended|popular|handpicked
    """
    base = _base_product_qs()

    # See-all handling
    view = (request.GET.get("view") or "").lower()
    RAILS = {
        "recommended": {
            "title": "Recommended",
            "filter": {"is_recommended": True},
            "key": "recommended",
        },
        "popular": {"title": "Most Popular", "filter": {"is_popular": True}, "key": "popular"},
        "handpicked": {
            "title": "Handpicked",
            "filter": {"is_handpicked": True},
            "key": "handpicked",
        },
    }
    if view in RAILS:
        qs = base.filter(**RAILS[view]["filter"]).order_by("home_rank", "-updated_at")
        paginator = Paginator(qs, 24)
        page_obj = paginator.get_page(request.GET.get("page") or 1)
        seo = {
            "title": f"{RAILS[view]['title']} – Store",
            "description": f"Browse all {RAILS[view]['title'].lower()} products.",
            "canonical": request.build_absolute_uri(),
        }
        return render(
            request,
            "storefront/home.html",
            {
                "page_obj": page_obj,
                "rail_title": RAILS[view]["title"],
                "rail_key": RAILS[view]["key"],
                "single_rail": view,
                "seo": seo,
                # breadcrumb(s) for potential use on Home (kept simple)
                "breadcrumb": [("Home", "storefront:home")],
                "breadcrumb3": _breadcrumb3_home_only(),
            },
        )

    # Curated rails (non-paginated)
    limit = 12
    sections = [
        {
            "key": "recommended",
            "title": "Recommended",
            "qs": base.filter(is_recommended=True).order_by("home_rank", "-updated_at")[:limit],
        },
        {
            "key": "popular",
            "title": "Most Popular",
            "qs": base.filter(is_popular=True).order_by("home_rank", "-updated_at")[:limit],
        },
        {
            "key": "handpicked",
            "title": "Handpicked",
            "qs": base.filter(is_handpicked=True).order_by("home_rank", "-updated_at")[:limit],
        },
    ]
    sections = [s for s in sections if s["qs"]]
    seo = {
        "title": "Store",
        "description": "Browse our latest recommended, popular, and handpicked products.",
        "canonical": request.build_absolute_uri(),
    }
    return render(
        request,
        "storefront/home.html",
        {
            "sections": sections,
            "seo": seo,
            "breadcrumb": [("Home", "storefront:home")],
            "breadcrumb3": _breadcrumb3_home_only(),
        },
    )


def category_listing(request, slug):
    # Build breadcrumbs for UI (pairs) and JSON-LD (triples)
    breadcrumb_ui = [("Home", "storefront:home"), (slug, None)]
    breadcrumb3 = [("Home", "storefront:home", None), (slug, None, None)]

    if Category is None:
        base_qs = _base_product_qs()
        page_obj, sort_key, SORT_OPTIONS = _sorted_paginated_products(request, base_qs)
        seo = {
            "title": slug,
            "description": f"Products in {slug}",
            "canonical": request.build_absolute_uri(),
        }
        return render(
            request,
            "storefront/category_listing.html",
            {
                "category": {"name": slug, "slug": slug},
                "page_obj": page_obj,
                "sort_key": sort_key,
                "SORT_OPTIONS": SORT_OPTIONS,
                "breadcrumb": breadcrumb_ui,
                "breadcrumb3": breadcrumb3,
                "seo": seo,
                "no_real_category_model": True,
            },
        )

    category = get_object_or_404(Category, slug=slug)
    base_qs = _base_product_qs().filter(category=category)
    page_obj, sort_key, SORT_OPTIONS = _sorted_paginated_products(request, base_qs)

    breadcrumb_ui = [("Home", "storefront:home"), (getattr(category, "name", category.slug), None)]
    breadcrumb3 = [
        ("Home", "storefront:home", None),
        (getattr(category, "name", category.slug), None, None),
    ]

    seo = {
        "title": getattr(category, "name", category.slug),
        "description": f"Products in {getattr(category, 'name', category.slug)}",
        "canonical": request.build_absolute_uri(),
    }
    return render(
        request,
        "storefront/category_listing.html",
        {
            "category": category,
            "page_obj": page_obj,
            "sort_key": sort_key,
            "SORT_OPTIONS": SORT_OPTIONS,
            "breadcrumb": breadcrumb_ui,
            "breadcrumb3": breadcrumb3,
            "seo": seo,
        },
    )


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.select_related("category").prefetch_related(
            Prefetch("variants", queryset=Variant.objects.filter(is_active=True).order_by("id")),
            "media",
        ),
        slug=slug,
        is_active=True,
    )

    variants = list(product.variants.all())

    # Pick the selected variant
    variant = None
    try:
        vid = int(request.GET.get("variant", "0"))
    except ValueError:
        vid = 0
    if vid:
        variant = next((v for v in variants if v.id == vid), None)
    if not variant and variants:
        variant = variants[0]

    # Breadcrumbs (UI: list of tuples that can include slug; JSON-LD: always triples)
    breadcrumb = [("Home", "storefront:home", None)]
    breadcrumb3 = [("Home", "storefront:home", None)]
    if getattr(product, "category", None):
        cat_label = getattr(product.category, "name", product.category.slug)
        cat_slug = product.category.slug
        breadcrumb.append((cat_label, "storefront:category", cat_slug))
        breadcrumb3.append((cat_label, "storefront:category", cat_slug))
    breadcrumb.append((product.title, None, None))
    breadcrumb3.append((product.title, None, None))

    # Prices
    prices = [Decimal(v.price_base or 0) for v in variants] or [Decimal(0)]
    min_price, max_price = min(prices), max(prices)
    currency = variants[0].currency if variants else "GBP"
    primary_image_url = None

    # Availability (compute purely in Python so the template does not need dict lookups)
    inv_by_variant = {
        iv.variant_id: int(iv.qty_available or 0)
        for iv in Inventory.objects.filter(variant__in=variants).only("variant_id", "qty_available")
    }
    supplier_active_ids = set(
        SupplierProduct.objects.filter(variant__in=variants, is_active=True)
        .values_list("variant_id", flat=True)
        .distinct()
    )

    # Build a simple set of IDs that are in stock; and a list the template can iterate
    in_stock_ids = set()
    variant_rows = []
    for v in variants:
        local_qty = inv_by_variant.get(v.id, 0)
        in_stock = (local_qty > 0) or (v.id in supplier_active_ids)
        if in_stock:
            in_stock_ids.add(v.id)

        # Fixed: Use getattr to safely access title attribute, fallback to sku or variant ID
        variant_title = getattr(v, "title", None) or getattr(v, "sku", None) or f"Variant {v.id}"

        variant_rows.append(
            {
                "id": v.id,
                "title": variant_title,
                "price": v.price_base or 0,
                "currency": v.currency or currency,
                "in_stock": in_stock,
            }
        )

    current_in_stock = bool(variant and variant.id in in_stock_ids)

    # Build offers for JSON-LD
    offers = []
    for row in variant_rows:
        variant_sku = None
        for v in variants:
            if v.id == row["id"]:
                variant_sku = getattr(v, "sku", f"VAR-{row['id']}")
                break
        if variant_sku is None:
            variant_sku = f"VAR-{row['id']}"

        offers.append(
            {
                "sku": variant_sku,
                "price": str(row["price"]),
                "priceCurrency": row["currency"],
                "availability": "https://schema.org/InStock"
                if row["in_stock"]
                else "https://schema.org/OutOfStock",
                "url": request.build_absolute_uri(f"{request.path}?variant={row['id']}"),
                "itemCondition": "https://schema.org/NewCondition",
            }
        )

    # Optional reviews (safe fallback)
    agg_rating, recent_reviews = None, []
    try:
        from reviews.models import Review

        qsr = Review.objects.filter(product=product, is_published=True)
        count = qsr.count()
        if count:
            from django.db import models

            avg = qsr.aggregate(avg=models.Avg("rating"))["avg"] or 0
            agg_rating = {"ratingValue": round(float(avg), 2), "reviewCount": count}
            for r in qsr.order_by("-created_at")[:3]:
                recent_reviews.append(
                    {
                        "author_name": getattr(r, "author_name", "Anonymous"),
                        "title": getattr(r, "title", "") or "Review",
                        "body": getattr(r, "body", "") or "",
                        "rating": int(getattr(r, "rating", 0) or 0),
                        "created": r.created_at.isoformat()
                        if getattr(r, "created_at", None)
                        else "",
                    }
                )
    except Exception:
        pass

    seo = {
        "title": product.title,
        "description": (product.description or "")[:160],
        "og_image": primary_image_url,
        "canonical": request.build_absolute_uri(),
    }

    return render(
        request,
        "storefront/product_detail.html",
        {
            "product": product,
            "variant": variant,
            "variants": variants,
            "variant_rows": variant_rows,  # <- simple data structure for the template
            "in_stock_ids": in_stock_ids,  # <- set for quick membership tests in template
            "current_in_stock": current_in_stock,  # <- boolean for the selected variant
            "breadcrumb": breadcrumb,
            "breadcrumb3": breadcrumb3,
            "seo": seo,
            "min_price": min_price,
            "max_price": max_price,
            "currency": currency,
            "primary_image_url": primary_image_url,
            "offers": offers,
            "agg_rating": agg_rating,
            "recent_reviews": recent_reviews,
        },
    )
