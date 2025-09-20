# orders/cart.py
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Iterable, List, Tuple, Union

CART_SESSION_KEY = "cart_v1"


@dataclass
class CartLine:
    product: any
    variant: any
    qty: int
    unit_price: Decimal

    @property
    def line_total(self) -> Decimal:
        return (self.unit_price or Decimal("0")) * int(self.qty or 0)


class Cart:
    """
    Session-backed cart that tolerates legacy shapes and stray keys.

    Canonical shape in the session:
        {
          "123": {"qty": 2},
          "456": {"qty": 1}
        }

    It also auto-migrates from nested/legacy shapes like:
        {"items": {"123": {"qty": 2}, ...}, "meta": {...}}
    """

    def __init__(self, request):
        self.request = request
        self.session = request.session
        raw = self.session.get(CART_SESSION_KEY, {})

        # ---- Auto-migrate legacy shapes ----
        # If it looks like {"items": {...}}, flatten to just the inner dict.
        if isinstance(raw, dict) and "items" in raw and isinstance(raw["items"], dict):
            raw = dict(raw["items"])  # flatten
            self.session[CART_SESSION_KEY] = raw
            self.session.modified = True

        # Ensure dict
        self._data: Dict[str, Union[int, Dict[str, int]]] = raw if isinstance(raw, dict) else {}
        # Strip obviously bad types early (but don't save yet; we only save on writes)

    # --------------- private helpers ---------------

    def _save(self) -> None:
        self.session[CART_SESSION_KEY] = self._data
        self.session.modified = True

    @staticmethod
    def _coerce_qty(payload: Union[int, Dict[str, int], None]) -> int:
        if payload is None:
            return 0
        if isinstance(payload, int):
            return payload
        if isinstance(payload, dict):
            try:
                return int(payload.get("qty", 0))
            except (TypeError, ValueError):
                return 0
        return 0

    # --------------- public API ---------------

    def items_raw(self) -> List[Tuple[int, int]]:
        """
        Returns a list of (variant_id, qty) from the session without DB hits.
        Skips any non-numeric keys gracefully.
        """
        out: List[Tuple[int, int]] = []
        for k, payload in list(self._data.items()):
            try:
                vid = int(k)
            except (TypeError, ValueError):
                # stray key (e.g., 'items', 'meta', etc.) — ignore
                continue
            qty = self._coerce_qty(payload)
            if qty > 0:
                out.append((vid, qty))
            else:
                # Drop zero/negative qty entries to keep session clean
                self._data.pop(k, None)
        return out

    def add(self, variant_id: int, qty: int = 1, replace: bool = False) -> None:
        key = str(int(variant_id))
        existing = self._coerce_qty(self._data.get(key))
        new_qty = int(qty) if replace else existing + int(qty)
        if new_qty <= 0:
            self._data.pop(key, None)
        else:
            self._data[key] = {"qty": new_qty}
        self._save()

    def update(self, variant_id: int, qty: int) -> None:
        self.add(variant_id, qty, replace=True)

    def remove(self, variant_id: int) -> None:
        self._data.pop(str(int(variant_id)), None)
        self._save()

    # ----- iteration & totals (with DB join for rich lines) -----
    def __iter__(self) -> Iterable[CartLine]:
        from catalog.models import Variant  # local import to avoid circulars

        pairs = self.items_raw()
        if not pairs:
            return iter(())
        ids = [vid for vid, _qty in pairs]
        variants = {v.id: v for v in Variant.objects.select_related("product").filter(id__in=ids)}
        lines: List[CartLine] = []
        for vid, qty in pairs:
            v = variants.get(vid)
            if not v:
                # variant no longer exists: silently skip here (validation removes later)
                continue
            lines.append(
                CartLine(
                    product=v.product,
                    variant=v,
                    qty=int(qty),
                    unit_price=(getattr(v, "price_base", None) or Decimal("0")),
                )
            )
        return iter(lines)

    @property
    def total_qty(self) -> int:
        return sum(qty for _vid, qty in self.items_raw())

    @property
    def total_price(self) -> Decimal:
        total = Decimal("0")
        for line in self:
            total += line.line_total
        return total

    @property
    def is_empty(self) -> bool:
        return self.total_qty <= 0

    def clear(self) -> None:
        self.session.pop(CART_SESSION_KEY, None)
        self.session.modified = True
