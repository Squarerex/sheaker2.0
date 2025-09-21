# storefront/views_catalog.py
from __future__ import annotations

from decimal import Decimal
from typing import Optional, Type

from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Count, Min, Prefetch, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string

from catalog.models import Inventory, Product, Variant

try:
    from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector

    POSTGRES_SEARCH_AVAILABLE = True
except ImportError:
    POSTGRES_SEARCH_AVAILABLE = False

try:
    from catalog.models import Category  # if your project has Category
    CATEGORY_MODEL: Optional[Type] = Category
except Exception:
    CATEGORY_MODEL = None

from providers.models import SupplierProduct

try:
    from reviews.models import Review
    REVIEW_MODEL: Optional[Type] = Review
except Exception:
    REVIEW_MODEL = None


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
        "title": ("title", "Title A—Z"),
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
            "title": f"{RAILS[view]['title']} — Store",
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

    if CATEGORY_MODEL is None:
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

    category = get_object_or_404(CATEGORY_MODEL, slug=slug)
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
    if REVIEW_MODEL:
        try:
            qsr = REVIEW_MODEL.objects.filter(product=product, is_published=True)
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


def search_view(request):
    """
    Advanced search with filtering, sorting, and pagination
    Auto-detects PostgreSQL for enhanced search capabilities
    """
    query = request.GET.get("q", "").strip()

    # Start with base queryset
    products = _base_product_qs()

    # Smart text search - PostgreSQL full-text search or fallback
    if query:
        # Check if we can use PostgreSQL full-text search
        is_postgres = connection.vendor == "postgresql" and POSTGRES_SEARCH_AVAILABLE

        if is_postgres:
            try:
                # Advanced PostgreSQL full-text search with ranking
                search_vector = (
                    SearchVector("title", weight="A")
                    + SearchVector("description", weight="B")
                    + SearchVector("brand", weight="C")
                )
                search_query = SearchQuery(query)

                products = (
                    products.annotate(
                        search=search_vector, rank=SearchRank(search_vector, search_query)
                    )
                    .filter(search=search_query)
                    .order_by("-rank", "-created_at")
                )

            except Exception:
                # Fallback if PostgreSQL search fails
                products = products.filter(
                    Q(title__icontains=query)
                    | Q(description__icontains=query)
                    | Q(brand__icontains=query)
                )
        else:
            # SQLite/MySQL compatible search
            products = products.filter(
                Q(title__icontains=query)
                | Q(description__icontains=query)
                | Q(brand__icontains=query)
            )

    # Category filtering
    selected_categories = request.GET.getlist("category")
    if selected_categories:
        products = products.filter(category__slug__in=selected_categories)

    # Brand filtering
    selected_brands = request.GET.getlist("brand")
    if selected_brands:
        products = products.filter(brand__in=selected_brands)

    # Price range filtering
    min_price = request.GET.get("min_price")
    max_price = request.GET.get("max_price")
    if min_price:
        try:
            min_price_decimal = Decimal(min_price)
            products = products.filter(variants__price_base__gte=min_price_decimal)
        except (ValueError, TypeError):
            min_price = None
    if max_price:
        try:
            max_price_decimal = Decimal(max_price)
            products = products.filter(variants__price_base__lte=max_price_decimal)
        except (ValueError, TypeError):
            max_price = None

    # Special filters
    show_recommended = bool(request.GET.get("recommended"))
    show_popular = bool(request.GET.get("popular"))
    show_handpicked = bool(request.GET.get("handpicked"))

    if show_recommended:
        products = products.filter(is_recommended=True)
    if show_popular:
        products = products.filter(is_popular=True)
    if show_handpicked:
        products = products.filter(is_handpicked=True)

    # Remove duplicates and annotate with min price for sorting
    products = products.distinct().annotate(min_price=Min("variants__price_base"))

    # Sorting
    sort_by = request.GET.get("sort", "newest")
    sort_options = {
        "newest": "-created_at",
        "price_low": "min_price",
        "price_high": "-min_price",
        "name": "title",
        "popularity": ["-is_popular", "-is_recommended", "-created_at"],
    }

    if sort_by in sort_options:
        order_by = sort_options[sort_by]
        if isinstance(order_by, list):
            products = products.order_by(*order_by)
        else:
            products = products.order_by(order_by)
    else:
        products = products.order_by("-created_at")

    # Get filter options for sidebar (only if we have a query or other filters)
    categories = []
    brands = []

    if (
        query
        or selected_categories
        or selected_brands
        or min_price
        or max_price
        or show_recommended
        or show_popular
        or show_handpicked
    ):
        # Base queryset for filters (before current filters are applied)
        base_for_filters = _base_product_qs()
        if query:
            base_for_filters = base_for_filters.filter(
                Q(title__icontains=query)
                | Q(description__icontains=query)
                | Q(brand__icontains=query)
            )

        # Get categories with product counts
        if CATEGORY_MODEL:
            categories = (
                CATEGORY_MODEL.objects.filter(products__in=base_for_filters, is_active=True)
                .annotate(product_count=Count("products", distinct=True))
                .filter(product_count__gt=0)
                .order_by("name")
            )

        # Get brands with product counts
        brand_counts = (
            base_for_filters.exclude(brand__isnull=True)
            .exclude(brand__exact="")
            .values("brand")
            .annotate(product_count=Count("id", distinct=True))
            .filter(product_count__gt=0)
            .order_by("brand")
        )

        brands = [{"name": b["brand"], "product_count": b["product_count"]} for b in brand_counts]

    # Pagination
    paginator = Paginator(products, 24)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    # Check if any filters are active
    has_active_filters = bool(
        selected_categories
        or selected_brands
        or min_price
        or max_price
        or show_recommended
        or show_popular
        or show_handpicked
    )

    # SEO
    seo_title = f"Search: {query}" if query else "Search Products"
    seo = {
        "title": f"{seo_title} - Store",
        "description": f"Search results for {query}" if query else "Search our product catalog",
        "canonical": request.build_absolute_uri(),
    }

    context = {
        "products": page_obj,
        "page_obj": page_obj,
        "is_paginated": page_obj.has_other_pages(),
        "search_query": query,
        "categories": categories,
        "brands": brands,
        "selected_categories": selected_categories,
        "selected_brands": selected_brands,
        "min_price": min_price,
        "max_price": max_price,
        "show_recommended": show_recommended,
        "show_popular": show_popular,
        "show_handpicked": show_handpicked,
        "sort_by": sort_by,
        "total_results": paginator.count,
        "has_active_filters": has_active_filters,
        "seo": seo,
    }

    return render(request, "storefront/search.html", context)


def search_suggestions_view(request):
    """
    AJAX endpoint for real-time search suggestions
    Auto-detects PostgreSQL for enhanced search capabilities
    """
    # Debug logging
    print(f"Search suggestions called with headers: {dict(request.headers)}")
    print(f"Is AJAX request: {request.headers.get('X-Requested-With') == 'XMLHttpRequest'}")

    if not request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"error": "Invalid request"}, status=400)

    query = request.GET.get("q", "").strip()
    print(f"Search query: '{query}'")

    if len(query) < 2:
        return JsonResponse(
            {
                "html": '<div class="p-2 text-sm text-gray-500">Start typing to see suggestions...</div>'
            }
        )

    try:
        # Check if we can use PostgreSQL full-text search
        is_postgres = connection.vendor == "postgresql" and POSTGRES_SEARCH_AVAILABLE

        # Get product suggestions with intelligent search
        if is_postgres:
            try:
                # Use PostgreSQL full-text search for suggestions
                search_vector = SearchVector("title", weight="A") + SearchVector(
                    "brand", weight="B"
                )
                search_query = SearchQuery(query)

                products = (
                    _base_product_qs()
                    .annotate(search=search_vector, rank=SearchRank(search_vector, search_query))
                    .filter(search=search_query)
                    .order_by("-rank")
                    .prefetch_related("media")[:6]
                )

            except Exception as e:
                print(f"PostgreSQL search failed: {e}")
                # Fallback to basic search
                products = (
                    _base_product_qs()
                    .filter(Q(title__icontains=query) | Q(brand__icontains=query))
                    .prefetch_related("media")[:6]
                )
        else:
            # SQLite/MySQL compatible search
            products = (
                _base_product_qs()
                .filter(Q(title__icontains=query) | Q(brand__icontains=query))
                .prefetch_related("media")[:6]
            )

        print(f"Found {len(products)} products")

        # Get brand suggestions
        brands = (
            Product.objects.filter(brand__icontains=query, is_active=True)
            .exclude(brand__isnull=True)
            .exclude(brand__exact="")
            .values_list("brand", flat=True)
            .distinct()[:4]
        )

        print(f"Found {len(brands)} brands")

        # Get category suggestions
        category_suggestions = []
        if CATEGORY_MODEL:
            category_suggestions = CATEGORY_MODEL.objects.filter(name__icontains=query, is_active=True)[
                :4
            ]

        print(f"Found {len(category_suggestions)} categories")

        # Render suggestions HTML
        suggestions_html = render_to_string(
            "storefront/_search_suggestions.html",
            {
                "query": query,
                "products": products,
                "brands": brands,
                "categories": category_suggestions,
            },
            request=request,
        )

        print(f"Rendered HTML length: {len(suggestions_html)}")

        return JsonResponse({"html": suggestions_html})

    except Exception as e:
        print(f"Search suggestions error: {e}")
        import traceback

        traceback.print_exc()

        return JsonResponse(
            {"html": '<div class="p-2 text-sm text-red-500">Error loading suggestions</div>'}
        )