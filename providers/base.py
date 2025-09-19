# providers/base.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Iterator, Mapping

Normalized = Dict[str, Any]  # unified structure for internal upsert


class BaseProvider(ABC):
    """
    Provider adapters must implement a minimal contract:
    - list_products(): yields raw supplier items (can be paginated generator).
    - get_product(external_id): fetch a single item.
    - map_to_internal(raw): convert supplier 'raw' into our Normalized dict.
    """

    def __init__(self, credentials: Mapping[str, Any]):
        self.credentials = credentials

    @abstractmethod
    def list_products(self, **kwargs) -> Iterator[Mapping[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_product(self, external_id: str) -> Mapping[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def map_to_internal(self, raw: Mapping[str, Any]) -> Normalized:
        """
        Returns a normalized payload with keys we can use to upsert Product & Variant(s).
        Minimal suggestions:
        {
            "product": {"title": "...", "description": "...", "brand": "...", "category": "...", ...},
            "variants": [
                {"sku": "...", "price": 10.5, "currency": "USD", "attributes": {...}, "weight": 0.2, "dims": {...}},
                ...
            ],
            "media": [
                {"url": "...", "kind": "image"},
            ],
            "external": {"external_id": "..."}  # for SupplierProduct
        }
        """
        raise NotImplementedError
