from django.conf import settings
from django.db import models


class ImportLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    filename = models.CharField(max_length=255)
    upsert = models.BooleanField(default=True)
    dry_run = models.BooleanField(default=False)
    counts = models.JSONField(default=dict, blank=True)
    errors = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["filename"]),
        ]

    def __str__(self) -> str:
        return f"ImportLog({self.filename})"
