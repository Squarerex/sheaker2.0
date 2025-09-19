# providers/tasks.py
from __future__ import annotations

from celery import shared_task

from providers.services.sync import sync_provider_products


@shared_task
def sync_provider(code: str):
    return sync_provider_products(provider_code=code, max_pages=2, page_size=50)
