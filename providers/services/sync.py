# providers/services/sync.py
from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta
from typing import Any, Dict, Mapping, Tuple

from django.core.cache import cache
from django.db import transaction
from django.db.models import ForeignKey, ManyToManyField, OneToOneField
from django.utils import timezone
from django.utils.timezone import now

from catalog.models import Product, Variant  # adjust import paths if different
from providers.adapters.cj import CJAdapter
from providers.models import ProviderAccount, ProviderSyncLog, SupplierProduct

log = logging.getLogger(__name__)


def _hash_raw(raw: dict) -> str:
    try:
        blob = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha1(blob).hexdigest()
    except Exception:
        return ""


def _has_field(model, name: str) -> bool:
    return any(f.name == name for f in model._meta.get_fields())


def _get_adapter_for(account: ProviderAccount):
    """Return the adapter for a provider and give it a callback to persist tokens."""

    def _save_tokens(access: str | None, refresh: str | None, access_expiry, refresh_expiry):
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

    code = (account.code or "").lower()
    if code == "cj":
        return CJAdapter(credentials=account.credentials_json, save_tokens=_save_tokens)
    raise ValueError(f"No adapter registered for provider code '{account.code}'")


def _norm_currency(value: str | None, default: str = "USD") -> str:
    return (value or default).upper()


def _product_defaults_from_mapped(p: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Build safe defaults for Product.objects.get_or_create(...).
    Avoid assigning relation fields (like category FK) with raw strings.
    """
    defaults: Dict[str, Any] = {
        "description": p.get("description") or "",
        "is_active": p.get("is_active", True),
    }

    # brand is usually a CharField in most schemas – include if exists
    product_fields = {f.name: f for f in Product._meta.get_fields()}
    if "brand" in product_fields:
        field = product_fields["brand"]
        # Only set if it's not a relation type
        if not isinstance(field, (ForeignKey, OneToOneField, ManyToManyField)):
            defaults["brand"] = p.get("brand")

    # category may be a FK in many schemas – only set if it's NOT relational
    if "category" in product_fields:
        field = product_fields["category"]
        if not isinstance(field, (ForeignKey, OneToOneField, ManyToManyField)):
            # In some schemas category is a CharField; accept the string
            defaults["category"] = p.get("category")

    return defaults


@transaction.atomic
def _upsert_product_tree(
    mapped: Mapping[str, Any],
    account: ProviderAccount,
    counts: Dict[str, int],
    *,
    dry_run: bool = False,
) -> Tuple[Product | None, Variant | None]:
    """
    Upserts Product + Variant(s), links SupplierProduct.
    Returns (product, last_variant_or_none). In dry_run, returns (None, None).
    """
    p = mapped["product"]

    if dry_run:
        counts["products_dry_run"] += 1
        product_obj = None
    else:
        # IMPORTANT: only pass safe defaults (no FK strings)
        defaults = _product_defaults_from_mapped(p)
        product_obj, _ = Product.objects.get_or_create(
            title=p["title"],
            defaults=defaults,
        )
        counts["products_upserted"] += 1

    last_variant_obj: Variant | None = None
    for v in mapped.get("variants", []):
        # Skip blank/missing SKU
        sku = str(v.get("sku") or "").strip()
        if not sku:
            counts["variants_skipped"] += 1
            continue

        currency = _norm_currency(v.get("currency"))

        if dry_run:
            counts["variants_dry_run"] = counts.get("variants_dry_run", 0) + 1
            counts["links_dry_run"] = counts.get("links_dry_run", 0) + 1
            continue

        assert product_obj is not None  # for type checking

        variant_obj, _created = Variant.objects.get_or_create(
            sku=sku,
            defaults={
                "product": product_obj,
                "attributes": v.get("attributes") or {},
                "price_base": v.get("price") or 0,
                "currency": currency,
                "weight": v.get("weight") or 0,
                "dims": v.get("dims") or {},
                "is_active": v.get("is_active", True),
            },
        )
        last_variant_obj = variant_obj
        counts["variants_upserted"] += 1

        # Link SupplierProduct (idempotent)
        external_id = mapped["external"]["external_id"]
        SupplierProduct.objects.update_or_create(
            provider_account=account,
            external_id=external_id,
            defaults={
                "variant": variant_obj,
                "raw": mapped.get("raw") or {},
                "is_active": True,
                "last_synced_at": timezone.now(),
            },
        )
        counts["links_upserted"] += 1

    # Media persistence is deferred to Phase 4
    return (None, None) if dry_run else (product_obj, last_variant_obj)


def sync_provider_products(
    *,
    provider_code: str,
    max_pages: int = 5,
    page_size: int = 50,
    dry_run: bool = False,
    limit: int | None = None,
    fetch_mode: str = "per_detail",
    filters: dict | None = None,
) -> Dict[str, int]:
    """
    Sync a single provider by code.

    - Logs start/end + counts + first error
    - Persists ProviderSyncLog for every attempt (including early lock failures)
    - Concurrency lock (15 min) to prevent overlap
    - Skips items with blank SKU; normalizes currency to uppercase
    - Respects optional limit and filters
    """
    account = ProviderAccount.objects.get(code=provider_code, is_active=True)
    adapter = _get_adapter_for(account)

    started = now()
    log_row = ProviderSyncLog.objects.create(
        provider_account=account,
        started_at=started,
        status="success",
        counts={},
        first_error="",
    )

    counts: Dict[str, int] = {
        "raw_seen": 0,
        "products_upserted": 0,
        "variants_upserted": 0,
        "variants_skipped": 0,
        "links_upserted": 0,
        "errors": 0,
    }
    first_error: str | None = None

    log.info(
        "sync.start provider=%s max_pages=%s page_size=%s dry_run=%s limit=%s filters=%s",
        provider_code,
        max_pages,
        page_size,
        dry_run,
        limit,
        filters,
    )

    lock_key = f"providers:sync_lock:{provider_code.lower()}"
    if not cache.add(lock_key, "1", timeout=60 * 15):
        # record and fail early
        log_row.status = "error"
        log_row.first_error = "Concurrency lock: another sync is running."
        log_row.finished_at = now()
        log_row.duration_ms = int((log_row.finished_at - started).total_seconds() * 1000)
        log_row.counts = counts
        log_row.save(
            update_fields=[
                "status",
                "first_error",
                "finished_at",
                "duration_ms",
                "counts",
            ]
        )
        raise RuntimeError(f"Sync already running for provider '{provider_code}'")

    try:
        for raw in adapter.list_products(
            page=1,
            page_size=page_size,
            max_pages=max_pages,
            filters=filters or {},
            fetch_mode=fetch_mode,  # NEW
        ):
            if limit and counts["raw_seen"] >= limit:
                break
            counts["raw_seen"] += 1
            try:
                mapped = adapter.map_to_internal(raw)

                # NEW: skip unchanged (if SupplierProduct has raw_hash)
                external_id = mapped["external"]["external_id"]
                do_hash = _has_field(SupplierProduct, "raw_hash")
                this_hash = _hash_raw(mapped.get("raw") or {}) if do_hash else ""

                if do_hash:
                    sp = (
                        SupplierProduct.objects.filter(
                            provider_account=account, external_id=external_id
                        )
                        .only("raw_hash", "last_synced_at")
                        .first()
                    )
                    if (
                        sp
                        and sp.raw_hash == this_hash
                        and sp.last_synced_at
                        and sp.last_synced_at > timezone.now() - timedelta(hours=24)
                    ):
                        counts["skipped_unchanged"] = counts.get("skipped_unchanged", 0) + 1
                        continue

                # proceed to upsert (passes through your dry_run)
                product_obj, last_variant_obj = _upsert_product_tree(
                    mapped, account, counts, dry_run=dry_run
                )

                # after the upsert, if not dry run, persist raw_hash (if field exists)
                if not dry_run and do_hash:
                    SupplierProduct.objects.filter(
                        provider_account=account, external_id=external_id
                    ).update(raw_hash=this_hash)

            except Exception as e:
                counts["errors"] += 1
                if first_error is None:
                    first_error = f"{type(e).__name__}: {e}"
                log.warning(
                    "sync.item_failed provider=%s err=%s",
                    provider_code,
                    e,
                    exc_info=False,
                )
    finally:
        cache.delete(lock_key)
        finished = now()
        duration_ms = int((finished - started).total_seconds() * 1000)
        status = "success" if counts["errors"] == 0 else "partial"
        if first_error:
            log_row.first_error = first_error
        log_row.status = status
        log_row.finished_at = finished
        log_row.duration_ms = duration_ms
        log_row.counts = counts
        log_row.save(
            update_fields=[
                "status",
                "finished_at",
                "duration_ms",
                "counts",
                "first_error",
            ]
        )
        log.info(
            "sync.end provider=%s counts=%s first_error=%s",
            provider_code,
            counts,
            first_error,
        )

    return counts
