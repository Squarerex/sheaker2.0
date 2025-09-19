from __future__ import annotations

from celery import shared_task
from django.core.management import call_command

from providers.services.sync import sync_provider_products


@shared_task
def cleanup_tmp_imports_task(hours: int = 24) -> None:
    # Runs your management command
    call_command("cleanup_tmp_imports", "--hours", str(hours))


@shared_task
def sync_provider(code: str):
    return sync_provider_products(provider_code=code, max_pages=2, page_size=50)
