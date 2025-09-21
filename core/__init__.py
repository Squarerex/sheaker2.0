from __future__ import annotations

# Make Celery optional so type-checking (and runtime without Celery) doesn’t crash
try:
    from .celery import app as celery_app  # noqa: F401
except Exception:  # ImportError, etc.
    celery_app = None
