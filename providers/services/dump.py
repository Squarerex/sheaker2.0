# providers/services/dump.py
from __future__ import annotations

import csv
import json
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from django.utils import timezone

from providers.adapters.cj import (
    FETCH_PER_DETAIL,
    CJAdapter,
)
from providers.models import ProviderSyncLog


def _to_float(x):
    try:
        return float(x)
    except Exception:
        return None


def _summarize(item: Mapping[str, Any]) -> Dict[str, Any]:
    pid = item.get("pid")
    title = item.get("productNameEn") or item.get("productName") or ""
    cat_path = item.get("categoryName") or ""
    variants = item.get("variants") or []
    skus = [str(v.get("variantSku") or "").strip() for v in variants if v.get("variantSku")]
    prices = [_to_float(v.get("variantSellPrice")) for v in variants]
    prices = [p for p in prices if p is not None]
    price_min = min(prices) if prices else None
    price_max = max(prices) if prices else None
    return {
        "pid": pid,
        "title": title,
        "category_path": cat_path,
        "variants_count": len(variants),
        "skus": "|".join(skus[:50]),
        "price_min": price_min,
        "price_max": price_max,
        "has_image": bool(item.get("productImage") or item.get("productImageSet")),
    }


def dump_provider_raw(
    *,
    account,
    page_size: int = 20,
    max_pages: int = 1,
    limit: Optional[int] = None,
    filters: Optional[Dict[str, Any]] = None,
    fetch_mode: str = FETCH_PER_DETAIL,
    bulk_size: int = 50,
    single_file: bool = True,  # <— new: default to one JSON file
) -> Tuple[Path, int, str]:
    """
    Fetch raw provider items and either:
      - write a SINGLE json file with {"index": {...}, "items": [...]}, or
      - write a ZIP archive (index.json, summary.csv, items/*.json)

    Returns: (path, count, content_type)
    """

    # persist refreshed tokens when adapter obtains them
    def _save_tokens(access, refresh, access_expiry, refresh_expiry):
        creds = dict(account.credentials_json or {})
        if access is not None:
            creds["access_token"] = access
        if refresh is not None:
            creds["refresh_token"] = refresh
        if access_expiry:
            creds["access_token_expires"] = access_expiry.isoformat()
        if refresh_expiry:
            creds["refresh_token_expires"] = refresh_expiry.isoformat()
        account.credentials_json = creds
        account.save(update_fields=["credentials_json"])

    adapter = CJAdapter(credentials=account.credentials_json, save_tokens=_save_tokens)

    ts = timezone.now().strftime("%Y%m%d-%H%M%S")
    base_dir = Path(tempfile.mkdtemp(prefix=f"cj_dump_{ts}_"))
    items: list[Mapping[str, Any]] = []
    summaries: list[dict] = []
    filters = filters or {}
    seen = 0

    for item in adapter.list_products(
        page=1,
        page_size=page_size,
        max_pages=max_pages,
        filters=filters,
        fetch_mode=fetch_mode,
        bulk_size=bulk_size,
    ):
        if limit and seen >= limit:
            break
        seen += 1
        items.append(item)
        summaries.append(_summarize(item))

    index = {
        "provider": account.code,
        "generated_at": ts,
        "count": seen,
        "filters": filters,
        "page_size": page_size,
        "max_pages": max_pages,
        "fetch_mode": fetch_mode,
        "bulk_size": bulk_size,
    }

    try:
        ProviderSyncLog.objects.create(
            provider_code=(
                account.code
                if hasattr(account, "code")
                else getattr(account, "provider_code", "unknown")
            ),
            mode="download",
            detail_level=fetch_mode,
            filters=filters,
            page_size=page_size,
            max_pages=max_pages,
            limit=limit,
            count_items=seen,
            request_count=getattr(adapter, "_req_count", None),
            first_error=None,
        )
    except Exception:
        pass

    if single_file:
        out_path = base_dir.with_suffix(".json")
        with out_path.open("w", encoding="utf-8") as f:
            json.dump({"index": index, "items": items}, f, ensure_ascii=False, indent=2)
        return out_path, seen, "application/json"

    # else: ZIP archive with per-item files (previous behavior)
    details_dir = base_dir / "items"
    details_dir.mkdir(parents=True, exist_ok=True)
    for it in items:
        pid = it.get("pid") or f"idx_{len(items)}"
        with (details_dir / f"{pid}.json").open("w", encoding="utf-8") as f:
            json.dump(it, f, ensure_ascii=False, indent=2)
    with (base_dir / "index.json").open("w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    with (base_dir / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "pid",
                "title",
                "category_path",
                "variants_count",
                "skus",
                "price_min",
                "price_max",
                "has_image",
            ],
        )
        writer.writeheader()
        for row in summaries:
            writer.writerow(row)

    try:
        ProviderSyncLog.objects.create(
            provider_code=(
                account.code
                if hasattr(account, "code")
                else getattr(account, "provider_code", "unknown")
            ),
            mode="download",
            detail_level=fetch_mode,
            filters=filters,
            page_size=page_size,
            max_pages=max_pages,
            limit=limit,
            count_items=seen,
            request_count=getattr(adapter, "_req_count", None),
            first_error=None,
        )
    except Exception:
        pass

    zip_path = base_dir.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(base_dir / "index.json", arcname="index.json")
        zf.write(base_dir / "summary.csv", arcname="summary.csv")
        for p in sorted(details_dir.glob("*.json")):
            zf.write(p, arcname=f"items/{p.name}")
    return zip_path, seen, "application/zip"
