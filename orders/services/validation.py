# orders/services/validation.py
from typing import Dict, List

from catalog.models import Inventory, Variant
from providers.models import SupplierProduct


def _has_active_supplier_product(variant: Variant) -> bool:
    return SupplierProduct.objects.filter(variant=variant, is_active=True).exists()


def _local_stock_qty(variant: Variant) -> int:
    inv = Inventory.objects.filter(variant=variant).first()
    return int(inv.qty_available) if inv and inv.qty_available is not None else 0


def _can_ship_placeholder(variant: Variant, destination_country_code: str) -> bool:
    # Replace with real logistics later.
    return True


def sanitize_cart(cart, destination_country_code: str) -> List[Dict]:
    """
    Rules:
      - remove if NO active supplier AND NO local stock
      - remove if qty > local stock AND NO supplier (true OOS)
      - remove if cannot ship (placeholder)
    Returns: [{"variant": Variant|ghost, "qty": int, "reason": str}, ...]
    """
    removed: List[Dict] = []

    # Build lookup for the variants currently referenced by the cart.
    variant_ids = [vid for vid, _qty in cart.items_raw()]
    variants = Variant.objects.filter(id__in=variant_ids, is_active=True).select_related("product")
    by_id = {v.id: v for v in variants}

    to_delete_ids: List[int] = []
    for vid, qty in cart.items_raw():
        v = by_id.get(vid)
        if not v:
            # stale / deleted variant
            to_delete_ids.append(vid)
            removed.append({"variant": Variant(id=vid), "qty": qty, "reason": "stale"})
            continue

        has_supplier = _has_active_supplier_product(v)
        local_qty = _local_stock_qty(v)
        can_ship = _can_ship_placeholder(v, destination_country_code)

        if not has_supplier and local_qty <= 0:
            to_delete_ids.append(vid)
            removed.append({"variant": v, "qty": qty, "reason": "no supplier + no local stock"})
            continue

        if qty > max(local_qty, 0) and not has_supplier:
            to_delete_ids.append(vid)
            removed.append({"variant": v, "qty": qty, "reason": "out-of-stock"})
            continue

        if not can_ship:
            to_delete_ids.append(vid)
            removed.append({"variant": v, "qty": qty, "reason": "cannot ship"})
            continue

    for vid in to_delete_ids:
        cart.remove(vid)

    return removed
