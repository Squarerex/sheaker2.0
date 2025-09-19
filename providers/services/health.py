# providers/services/health.py
from __future__ import annotations

from typing import Any, Dict

from providers.adapters.cj import CJAdapter
from providers.models import ProviderAccount


def ping_provider(account: ProviderAccount) -> Dict[str, Any]:
    code = account.code.lower()
    if code == "cj":
        adapter = CJAdapter(credentials=account.credentials_json)
        # light call: try to list a single page
        gen = adapter.list_products(page=1, page_size=1, max_pages=1)
        first = next(gen, None)  # don't consume more than needed
        return {"ok": True, "sample_found": bool(first)}
    return {"ok": False, "error": f"Unknown provider code: {account.code}"}
