from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from providers.adapters.cj import CJAdapter
from providers.models import ProviderAccount


def _to_float(x) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def _summarize(detail: Mapping[str, Any]) -> Dict[str, Any]:
    """Make a one-line summary for quick eyeballing & CSV."""
    pid = detail.get("pid")
    title = detail.get("productNameEn") or detail.get("productName") or ""
    # CJ often sends a breadcrumb-like string such as "Jewelry & Watches > Fashion Jewelry"
    cat_path = detail.get("categoryName") or ""
    variants = detail.get("variants") or []
    skus = [
        str(v.get("variantSku") or "").strip() for v in variants if v.get("variantSku")
    ]
    prices = [_to_float(v.get("variantSellPrice")) for v in variants]
    prices = [p for p in prices if p is not None]
    price_min = min(prices) if prices else None
    price_max = max(prices) if prices else None
    return {
        "pid": pid,
        "title": title,
        "category_path": cat_path,
        "variants_count": len(variants),
        "skus": "|".join(skus[:20]),
        "price_min": price_min,
        "price_max": price_max,
        "has_image": bool(detail.get("productImage")),
    }


class Command(BaseCommand):
    help = "Fetch raw CJ product JSON to disk for inspection (filters: keyword, categoryId)."

    def add_arguments(self, parser):
        parser.add_argument("--code", default="cj", help="Provider code (default: cj)")
        parser.add_argument(
            "--out", default=None, help="Output dir (default: ./_cj_dump/<timestamp>/)"
        )
        parser.add_argument(
            "--max-pages",
            type=int,
            default=1,
            help="How many list pages to walk (default 1)",
        )
        parser.add_argument(
            "--page-size", type=int, default=20, help="Items per page (<=200)"
        )
        parser.add_argument(
            "--limit", type=int, default=None, help="Hard cap on # of detailed products"
        )
        parser.add_argument(
            "--keyword", default=None, help="CJ /product/list ?keyword="
        )
        parser.add_argument(
            "--category-id",
            dest="category_id",
            default=None,
            help="CJ /product/list ?categoryId=",
        )

    def handle(self, *args, **opts):
        # Resolve account + adapter
        try:
            account = ProviderAccount.objects.get(code=opts["code"], is_active=True)
        except ProviderAccount.DoesNotExist as e:
            raise CommandError(
                f"Provider '{opts['code']}' not found or inactive"
            ) from e

        # Persist refreshed tokens back to credentials_json
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

        adapter = CJAdapter(
            credentials=account.credentials_json, save_tokens=_save_tokens
        )

        # Output directories
        ts = timezone.now().strftime("%Y%m%d-%H%M%S")
        base = Path(opts["out"] or f"_cj_dump/{ts}")
        details_dir = base / "details"
        base.mkdir(parents=True, exist_ok=True)
        details_dir.mkdir(parents=True, exist_ok=True)

        # Filters pass straight to /product/list
        filters: Dict[str, Any] = {}
        if opts.get("keyword"):
            filters["keyword"] = opts["keyword"]
        if opts.get("category_id"):
            filters["categoryId"] = opts["category_id"]

        page_size = int(opts["page_size"])
        max_pages = int(opts["max_pages"])
        limit = opts.get("limit")

        # Fetch + dump
        seen = 0
        summaries: list[dict] = []
        self.stdout.write(
            self.style.NOTICE(
                f"Fetching CJ: max_pages={max_pages} page_size={page_size} "
                f"limit={limit or '∞'} filters={filters or '{}'} → {base}"
            )
        )

        try:
            for detail in adapter.list_products(
                page=1, page_size=page_size, max_pages=max_pages, filters=filters
            ):
                if limit and seen >= limit:
                    break
                seen += 1

                # Write raw JSON detail
                pid = detail.get("pid") or f"idx_{seen}"
                out_path = details_dir / f"{pid}.json"
                with out_path.open("w", encoding="utf-8") as f:
                    json.dump(detail, f, ensure_ascii=False, indent=2)

                # Track summary row
                summaries.append(_summarize(detail))
        except Exception as e:
            # Show a short message and keep whatever we already saved
            raise CommandError(f"Fetch failed after {seen} items: {e}") from e

        # Write index & CSV
        with (base / "index.json").open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "generated_at": ts,
                    "count": seen,
                    "filters": filters,
                    "page_size": page_size,
                    "max_pages": max_pages,
                    "dir": str(details_dir),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

        csv_path = base / "summary.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
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

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Saved {seen} product JSON files under {details_dir}\nSummary: {csv_path}"
            )
        )
