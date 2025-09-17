from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import ImportLog


@admin.register(ImportLog)
class ImportLogAdmin(admin.ModelAdmin):
    list_display = (
        "filename",
        "user",
        "upsert",
        "dry_run",
        "created_at",
        "preview_link",
    )
    readonly_fields = ("counts", "errors", "created_at", "preview_link")
    search_fields = ("filename", "user__username")
    ordering = ("-created_at",)
    list_per_page = 50

    def preview_link(self, obj):
        url = (
            reverse("dashboard:product_upload_preview")
            + f"?token={obj.filename}&upsert={'1' if obj.upsert else '0'}"
        )
        return format_html(
            '<a href="{}" class="button" target="_blank" rel="noopener">Reopen Preview</a>',
            url,
        )

    preview_link.short_description = "Preview"
