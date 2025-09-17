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
]


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
        # Collect headers seen across items
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
    # Keep unmapped keys that might already match normalized names
    for k in NORMALIZED_FIELDS:
        if k not in out and k in raw:
            out[k] = raw[k]
    return out


def _normalize_row(raw_in: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize to your schema. Accept flexible names; we already may have applied mapping above.
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


@transaction.atomic
def _upsert_one(n: Dict[str, Any]) -> Tuple[bool, bool, int, str]:
    """
    Returns: (product_created, variant_created, media_created, inventory_action)
      inventory_action in {"", "set", "increment"}
    """
    sku = n["sku"]
    price_base = Decimal(str(n["price"]))
    currency = str(n.get("currency", "USD")).upper()
    if currency not in VALID_CURRENCIES:
        currency = "USD"  # last-resort fallback; validation should have caught this.

    # Taxonomy
    cat = _get_or_create_category(n.get("category_name", ""))
    subcat = _get_or_create_subcategory(cat, n.get("subcategory_name", ""))

    variant = Variant.objects.select_related("product").filter(sku=sku).first()
    product_created = False
    variant_created = False
    media_created = 0
    inventory_action = ""

    if variant:
        # UPDATE
        p = variant.product
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

        variant.price_base = price_base
        variant.currency = currency
        if n.get("weight") not in (None, ""):
            try:
                variant.weight = Decimal(str(n["weight"]))
            except InvalidOperation:
                pass
        if isinstance(n.get("dims"), dict):
            variant.dims = n["dims"]
        variant.save()

    else:
        # CREATE
        p = Product.objects.create(
            title=n["title"],
            description=n.get("description", ""),
            brand=n.get("brand", ""),
            category=cat,
            subcategory=subcat,
            is_active=True,
        )
        product_created = True

        variant = Variant.objects.create(
            product=p,
            sku=sku,
            attributes={},
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
    # Your model: Inventory(variant, qty_available, safety_stock, warehouse)  :contentReference[oaicite:5]{index=5}
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

    # --- Media from external URLs ---
    for url in n.get("media_urls", []):
        if not url:
            continue
        # Your Media validates kind/content alignment; for external URL, use kind='external' + url.  :contentReference[oaicite:6]{index=6}
        Media.objects.get_or_create(
            product=variant.product,
            variant=None,
            kind=Media.KIND_EXTERNAL,
            url=str(url),
            defaults={"alt": n.get("title", ""), "is_main": False},
        )
        media_created += 1

    return product_created, variant_created, media_created, inventory_action


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

    for idx, row in enumerate(preview["rows"]):
        if row["action"] in ("error", "skip"):
            if row["action"] == "error":
                results["errors"].append(
                    {"row_index": idx, "error": "; ".join(row["errors"])}
                )
            continue

        if dry_run:
            # "Would do" counts
            if row["action"] == "create":
                results["products_created"] += 1
                results["variants_created"] += 1
            elif row["action"] == "update":
                results["products_updated"] += 1
                results["variants_updated"] += 1

            if row.get("media_urls"):
                results["media_created"] += len(row["media_urls"])

            if row.get("qty_available") not in (None, ""):
                if (row.get("stock_mode") or "set") == "increment":
                    results["inventory_incremented"] += 1
                else:
                    results["inventory_set"] += 1
            continue

        try:
            p_created, v_created, media_c, inv_act = _upsert_one(row)
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
