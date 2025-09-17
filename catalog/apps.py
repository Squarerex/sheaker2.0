# catalog/apps.py
from __future__ import annotations

from django.apps import AppConfig


class CatalogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "catalog"

    def ready(self) -> None:
        # Import signal handlers
        from . import signals  # noqa: F401
