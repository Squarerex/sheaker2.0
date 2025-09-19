from __future__ import annotations

import pathlib
import re
import tempfile
import time

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


@shared_task(name="core.cleanup_provider_dumps")
def cleanup_provider_dumps(days: int = 2) -> int:
    """
    Delete cj_dump_*.json/.zip temp files older than N days from system temp dir.
    Returns number of files removed.
    """
    cutoff = time.time() - days * 86400
    tmpdir = pathlib.Path(tempfile.gettempdir())
    pat = re.compile(r"^cj_dump_\d{8}-\d{6}\.(json|zip)$")
    removed = 0
    for p in tmpdir.iterdir():
        if not p.is_file():
            continue
        if not pat.match(p.name):
            continue
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        except Exception:
            pass
    return removed
