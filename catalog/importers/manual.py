from __future__ import annotations

import csv
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from django.db import transaction
from django.utils.text import slugify

from catalog.models import (
    CURRENCY_CHOICES,
    Category,
    Inventory,
    Media,
    Product,
    Subcategory,
    Variant,
)

REQUIRED_FIELDS = ("title", "sku", "price")
VALID_CURRENCIES = {
    c[0].upper() for c in CURRENCY_CHOICES
}  # e.g. {"USD","EUR","GBP","NGN"}

# Which normalized keys we accept (used by column-mapping UI)
NORMALIZED_FIELDS = [
    "title",
    "description",
    "brand",
    "category_name",
    "subcategory_name",
    "sku",
    "price",
    "currency",
    "weight",
    "dims",
    "media_urls",
    # inventory-related
    "qty_available",
    "safety_stock",
    "warehouse",
    "stock_mode",
    # product identity (optional; helps group variants)
    "product_key",
    "product_productSku",
    # NEW: carry parsed CJ data into Variant
    "attributes",  # dict (e.g., {"color": "...", "size": "..."})
    "vid",  # CJ variant ID (optional)
    "variant_key",  # CJ variantKey (optional)
]

# ---------------- I/O helpers ----------------


def _ext(path: Path) -> str:
    return path.suffix.lower()


def _load_rows_and_headers(path: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Return (rows, source_headers) for JSON/CSV."""
    if _ext(path) == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "items" in data:
            data = data["items"]
        if not isinstance(data, list):
            raise ValueError("JSON must be a list or {'items': [...]} format.")
        headers = sorted(
            {k for row in data if isinstance(row, dict) for k in row.keys()}
        )
        return data, headers

    if _ext(path) == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            headers = list(reader.fieldnames or [])
            return rows, headers

    raise ValueError("Unsupported file type; only .json or .csv.")


def _apply_mapping(raw: Dict[str, Any], mapping: Dict[str, str]) -> Dict[str, Any]:
    """
    Map raw["supplier_header"] -> normalized key (e.g. 'SKU' -> 'sku').
    mapping is {normalized_field: supplier_header}. If supplier header missing, value is left out.
    """
    out: Dict[str, Any] = {}
    for norm_key, supplier_key in mapping.items():
        if supplier_key:
            out[norm_key] = raw.get(supplier_key)
    # Keep unmapped keys that already match normalized names (including product_key fields)
    for k in NORMALIZED_FIELDS:
        if k not in out and k in raw:
            out[k] = raw[k]
    return out


# ---------------- Normalization & validation ----------------


def _normalize_row(raw_in: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize to your schema. Accept flexible names; we may already have applied mapping above.
    Pass through product_key / product_productSku if present (used for grouping).
    """
    raw = raw_in or {}

    title = str(raw.get("title") or raw.get("name") or "").strip()
    description = str(raw.get("description") or raw.get("desc") or "").strip()
    brand = str(raw.get("brand") or "").strip()

    category_name = (raw.get("category_name") or raw.get("category") or "").strip()
    subcategory_name = (
        raw.get("subcategory_name") or raw.get("subcategory") or ""
    ).strip()

    sku = str(raw.get("sku") or raw.get("SKU") or "").strip()
    price = raw.get("price") or raw.get("price_base") or raw.get("amount")
    currency = str(raw.get("currency") or "USD").upper()

    weight = raw.get("weight")
    dims = raw.get("dims") or {}
    media_urls = raw.get("media_urls") or raw.get("images") or []

    # optional product identity fields for grouping
    product_key = str(raw.get("product_key") or "").strip()
    product_productSku = str(raw.get("product_productSku") or "").strip()

    # CJ-derived additions
    attributes = (
        raw.get("attributes") or {}
    )  # dict with standardized fields like color/size
    vid = raw.get("vid")  # optional CJ variant id
    variant_key = raw.get("variant_key")  # the raw variantKey string (for debugging)

    # Inventory extensions
    qty_available = raw.get("qty_available")
    safety_stock = raw.get("safety_stock")
    warehouse = raw.get("warehouse")
    stock_mode = (
        raw.get("stock_mode") or "set"
    ).lower()  # "set" (default) or "increment"

    if not isinstance(media_urls, list):
        media_urls = []
    if not isinstance(dims, dict):
        dims = {}
    if attributes is None or not isinstance(attributes, dict):
        attributes = {}

    return {
        "title": title,
        "description": description,
        "brand": brand,
        "category_name": category_name,
        "subcategory_name": subcategory_name,
        "sku": sku,
        "price": price,
        "currency": currency,
        "weight": weight,
        "dims": dims,
        "media_urls": media_urls,
        "qty_available": qty_available,
        "safety_stock": safety_stock,
        "warehouse": warehouse,
        "stock_mode": stock_mode,
        "product_key": product_key,
        "product_productSku": product_productSku,
        # pass-through CJ extras
        "attributes": attributes,
        "vid": vid,
        "variant_key": variant_key,
    }


def _validate_row(n: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    for key in REQUIRED_FIELDS:
        if not str(n.get(key, "")).strip():
            errors.append(f"Missing required field: {key}")

    # price must be Decimal-parsable
    try:
        Decimal(str(n["price"]))
    except Exception:
        errors.append("price must be a valid number (Decimal).")

    # currency must be in your model choices (show allowed)
    curr = str(n.get("currency", "")).upper()
    if curr and curr not in VALID_CURRENCIES:
        errors.append(
            f"currency '{curr}' must be one of: {', '.join(sorted(VALID_CURRENCIES))}"
        )

    # dims, if provided, must be a dict
    if n.get("dims") and not isinstance(n["dims"], dict):
        errors.append("dims must be an object like {'l':10,'w':5,'h':3,'unit':'cm'}.")

    # attributes, if provided, must be a dict
    if n.get("attributes") and not isinstance(n["attributes"], dict):
        errors.append(
            "attributes must be an object (e.g., {'color':'Black','size':'M'})."
        )

    # inventory numeric checks if present
    if n.get("qty_available") not in (None, ""):
        try:
            int(n["qty_available"])
        except Exception:
            errors.append("qty_available must be integer.")
    if n.get("safety_stock") not in (None, ""):
        try:
            int(n["safety_stock"])
        except Exception:
            errors.append("safety_stock must be integer.")
    if n.get("stock_mode") and n["stock_mode"] not in ("set", "increment"):
        errors.append("stock_mode must be 'set' or 'increment'.")

    return errors


def _classify_action(n: Dict[str, Any], upsert: bool) -> str:
    exists = Variant.objects.filter(sku=n["sku"]).exists()
    if exists and upsert:
        return "update"
    if exists and not upsert:
        return "skip"
    return "create"


# ---------------- Preview ----------------


def parse_file_to_preview(
    path: Path,
    upsert: bool,
    *,
    mapping: Optional[Dict[str, str]] = None,
    page: int = 1,
    per_page: int = 500,
) -> Dict[str, Any]:
    """
    Returns preview with pagination and original headers for mapping UI.
    """
    rows_raw, source_headers = _load_rows_and_headers(path)

    # Apply mapping (CSV-friendly). mapping is {normalized_key: supplier_header}
    mapped_rows = []
    mapping = mapping or {}
    for raw in rows_raw:
        if mapping:
            raw = _apply_mapping(raw, mapping)
        mapped_rows.append(raw)

    # Build preview rows (full list)
    rows_full: List[Dict[str, Any]] = []
    stats = {"total": 0, "to_create": 0, "to_update": 0, "to_skip": 0, "errors": 0}
    for raw in mapped_rows:
        n = _normalize_row(raw)
        errs = _validate_row(n)
        action = _classify_action(n, upsert) if not errs else "error"
        if action == "create":
            stats["to_create"] += 1
        elif action == "update":
            stats["to_update"] += 1
        elif action == "skip":
            stats["to_skip"] += 1
        elif action == "error":
            stats["errors"] += 1
        rows_full.append({**n, "errors": errs, "action": action})
        stats["total"] += 1

    # Pagination slice
    total = stats["total"]
    per_page = max(50, min(per_page, 2000))
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    end = start + per_page
    rows_page = rows_full[start:end]

    return {
        "rows": rows_page,
        "stats": stats,
        "upsert": upsert,
        "token": path.name,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "source_headers": source_headers,
        "mapping": mapping,  # echo back current mapping
        "allowed_currencies": sorted(VALID_CURRENCIES),
    }


# ---------------- Category helpers ----------------


def _get_or_create_category(name: str) -> Optional[Category]:
    if not name:
        return None
    obj, _ = Category.objects.get_or_create(name=name, defaults={"slug": slugify(name)})
    return obj


def _get_or_create_subcategory(
    cat: Optional[Category], name: str
) -> Optional[Subcategory]:
    if not name or not cat:
        return None
    obj, _ = Subcategory.objects.get_or_create(
        category=cat, name=name, defaults={"slug": slugify(name)}
    )
    return obj


# ---------------- Upsert (grouped by product_key) ----------------


@transaction.atomic
def _upsert_one(
    n: Dict[str, Any], *, product_cache: Dict[str, Product]
) -> Tuple[bool, bool, int, str]:
    """
    Upsert a single row.
    Returns: (product_created, variant_created, media_created, inventory_action)
      inventory_action in {"", "set", "increment"}
    Groups by n["product_key"] to avoid creating duplicate products per variant.
    """
    sku = n["sku"]
    price_base = Decimal(str(n["price"]))
    currency = str(n.get("currency", "USD")).upper()
    if currency not in VALID_CURRENCIES:
        currency = "USD"  # last-resort fallback; validation should have caught this.

    # Taxonomy (per row; first row for a product will effectively set it)
    cat = _get_or_create_category(n.get("category_name", ""))
    subcat = _get_or_create_subcategory(cat, n.get("subcategory_name", ""))

    product_created = False
    variant_created = False
    media_created = 0
    inventory_action = ""

    # If the variant already exists, we update it and its product and also hydrate cache.
    variant = Variant.objects.select_related("product").filter(sku=sku).first()
    if variant:
        p = variant.product
        key = (n.get("product_key") or "").strip()
        if key and key not in product_cache:
            product_cache[key] = p

        # UPDATE product fields
        if n["title"]:
            p.title = n["title"]
        if n.get("description") is not None:
            p.description = n["description"]
        if n.get("brand"):
            p.brand = n["brand"]
        if cat:
            p.category = cat
        if subcat:
            p.subcategory = subcat
        p.save()

        # UPDATE variant fields
        variant.price_base = price_base
        variant.currency = currency
        # attributes (overwrite or merge policy; we overwrite with latest)
        if isinstance(n.get("attributes"), dict) and n["attributes"]:
            variant.attributes = n["attributes"]
        if n.get("weight") not in (None, ""):
            try:
                variant.weight = Decimal(str(n["weight"]))
            except InvalidOperation:
                pass
        if isinstance(n.get("dims"), dict):
            variant.dims = n["dims"]
        variant.is_active = True
        variant.save()

    else:
        # CREATE or re-use existing product based on product_key
        key = (n.get("product_key") or "").strip()
        if key and key in product_cache:
            p = product_cache[key]
        else:
            p = Product.objects.create(
                title=n["title"],
                description=n.get("description", ""),
                brand=n.get("brand", ""),
                category=cat,
                subcategory=subcat,
                is_active=True,
            )
            product_created = True
            if key:
                product_cache[key] = p

        # CREATE variant under that product
        variant = Variant.objects.create(
            product=p,
            sku=sku,
            attributes=(n.get("attributes") or {}),  # <-- write attributes on create
            price_base=price_base,
            currency=currency,
            weight=(
                Decimal(str(n["weight"])) if n.get("weight") not in (None, "") else None
            ),
            dims=n.get("dims") or {},
            is_active=True,
        )
        variant_created = True

    # --- Inventory (OneToOne) ---
    if (
        n.get("qty_available") not in (None, "")
        or n.get("safety_stock") not in (None, "")
        or n.get("warehouse")
    ):
        inv, _ = Inventory.objects.get_or_create(variant=variant)
        if n.get("qty_available") not in (None, ""):
            qty = int(n["qty_available"])
            mode = n.get("stock_mode", "set")
            if mode == "increment":
                inv.qty_available = max(0, inv.qty_available + qty)
                inventory_action = "increment"
            else:
                inv.qty_available = max(0, qty)
                inventory_action = "set"
        if n.get("safety_stock") not in (None, ""):
            inv.safety_stock = max(0, int(n["safety_stock"]))
        if n.get("warehouse"):
            inv.warehouse = str(n["warehouse"])
        inv.save()

    # --- Media from external URLs (attach to VARIANT) ---
    urls = [u for u in (n.get("media_urls") or []) if u]
    if urls:
        existing = set(
            Media.objects.filter(variant=variant, kind=Media.KIND_EXTERNAL).values_list(
                "url", flat=True
            )
        )
        has_media = variant.media.exists()
        for idx, url in enumerate(urls):
            if url in existing:
                continue
            is_main = False
            # If the variant has no media at all yet, make the FIRST created one main
            if not has_media and media_created == 0 and idx == 0:
                is_main = True
            Media.objects.create(
                product=variant.product,
                variant=variant,
                kind=Media.KIND_EXTERNAL,
                url=str(url),
                alt=n.get("title", "")[:255],
                is_main=is_main,
                position=0 if is_main else 1,
            )
            media_created += 1
            has_media = True

    return product_created, variant_created, media_created, inventory_action


# ---------------- Commit ----------------


def commit_import_payload(
    path: Path,
    update_existing: bool,
    *,
    dry_run: bool = False,
    mapping: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    preview = parse_file_to_preview(path, upsert=update_existing, mapping=mapping)
    results = {
        "products_created": 0,
        "products_updated": 0,
        "variants_created": 0,
        "variants_updated": 0,
        "media_created": 0,
        "inventory_set": 0,
        "inventory_incremented": 0,
        "errors": [],
    }

    # Cache of product_key -> Product to keep all variants under the same product within this run
    product_cache: Dict[str, Product] = {}

    for idx, row in enumerate(preview["rows"]):
        if row["action"] in ("error", "skip"):
            if row["action"] == "error":
                results["errors"].append(
                    {"row_index": idx, "error": "; ".join(row["errors"])}
                )
            continue

        if dry_run:
            # counts are per-variant (fine for summaries)
            if row["action"] == "create":
                results["products_created"] += 1  # may overcount in dry-run, acceptable
                results["variants_created"] += 1
            elif row["action"] == "update":
                results["products_updated"] += 1
                results["variants_updated"] += 1

            if row.get("media_urls"):
                # approximate count; actual commit avoids duplicates
                results["media_created"] += len([u for u in row["media_urls"] if u])
            if row.get("qty_available") not in (None, ""):
                if (row.get("stock_mode") or "set") == "increment":
                    results["inventory_incremented"] += 1
                else:
                    results["inventory_set"] += 1
            continue

        try:
            p_created, v_created, media_c, inv_act = _upsert_one(
                row, product_cache=product_cache
            )
            if p_created:
                results["products_created"] += 1
            else:
                results["products_updated"] += 1
            if v_created:
                results["variants_created"] += 1
            else:
                results["variants_updated"] += 1
            results["media_created"] += media_c
            if inv_act == "set":
                results["inventory_set"] += 1
            elif inv_act == "increment":
                results["inventory_incremented"] += 1
        except Exception as e:
            results["errors"].append({"row_index": idx, "error": str(e)})

    return results
