# providers/models.py
from __future__ import annotations

from django.db import models
from django.utils import timezone


class ProviderAccount(models.Model):
    """
    Represents a single external supplier account (e.g., CJ).
    `credentials_json` can store API keys, tokens, etc. (encrypted at rest if you use a secrets backend).
    """

    code = models.SlugField(max_length=50, unique=True, help_text="Short code, e.g., 'cj'")
    name = models.CharField(max_length=100)
    priority = models.PositiveIntegerField(default=100, help_text="Lower number = higher priority")
    credentials_json = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["priority", "code"]

    def __str__(self) -> str:
        return f"{self.code} ({'active' if self.is_active else 'inactive'})"


class SupplierProduct(models.Model):
    """
    Links an external supplier product to an internal Variant.
    """

    provider_account = models.ForeignKey(
        ProviderAccount, on_delete=models.CASCADE, related_name="supplier_products"
    )
    variant = models.ForeignKey(
        "catalog.Variant", on_delete=models.CASCADE, related_name="supplier_links"
    )
    external_id = models.CharField(
        max_length=255, help_text="Supplier's product/variant identifier"
    )
    raw = models.JSONField(
        default=dict, blank=True, help_text="Original raw payload for traceability"
    )
    is_active = models.BooleanField(default=True)
    last_synced_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider_account", "external_id"],
                name="uq_provider_external_id",
            )
        ]
        indexes = [
            models.Index(fields=["variant"]),
            models.Index(fields=["provider_account"]),
            models.Index(fields=["provider_account", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.provider_account.code}:{self.external_id} → {self.variant_id}"


class ProviderSyncLog(models.Model):
    STATUS_CHOICES = [
        ("success", "Success"),
        ("partial", "Partial"),  # completed with some errors
        ("error", "Error"),  # failed very early
    ]

    provider_account = models.ForeignKey(
        "providers.ProviderAccount",
        on_delete=models.CASCADE,
        related_name="sync_logs",
    )
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="success")
    counts = models.JSONField(default=dict, blank=True)
    first_error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["provider_account", "-started_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"{self.provider_account.code} @ {self.started_at:%Y-%m-%d %H:%M:%S} [{self.status}]"
