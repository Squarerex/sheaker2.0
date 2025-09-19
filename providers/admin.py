# providers/admin.py
from django.contrib import admin, messages
from django.db import models

from providers.models import ProviderSyncLog

# ---- Safe fallback: use AdminJSONFieldWidget if available, else AdminTextareaWidget
try:
    from django.contrib.admin.widgets import AdminJSONFieldWidget as _JSONWidget
except Exception:
    from django.contrib.admin.widgets import AdminTextareaWidget as _JSONWidget

from providers.models import ProviderAccount, SupplierProduct
from providers.services.health import ping_provider
from providers.services.sync import sync_provider_products


# Admin action must be defined before it's referenced
@admin.action(description="Sync selected providers now")
def sync_selected_providers(modeladmin, request, queryset):
    total = 0
    for account in queryset:
        if not account.is_active:
            messages.warning(request, f"Skipped {account.code}: inactive")
            continue
        try:
            result = sync_provider_products(
                provider_code=account.code, max_pages=1, page_size=50
            )
            messages.success(request, f"{account.code} synced: {result}")
            total += 1
        except Exception as e:
            messages.error(request, f"{account.code} failed: {e}")
    if total:
        messages.info(request, f"Synced {total} provider(s).")


@admin.action(description="Test credentials (ping)")
def test_selected_providers(modeladmin, request, queryset):
    for account in queryset:
        try:
            result = ping_provider(account)
            if result.get("ok"):
                messages.success(
                    request,
                    f"{account.code} ping OK (sample_found={result.get('sample_found')})",
                )
            else:
                messages.error(
                    request, f"{account.code} ping failed: {result.get('error')}"
                )
        except Exception as e:
            messages.error(request, f"{account.code} ping exception: {e}")


# In ProviderAccountAdmin.actions, include the new action:
actions = [sync_selected_providers, test_selected_providers]


@admin.register(ProviderAccount)
class ProviderAccountAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "priority", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")
    actions = [sync_selected_providers]

    # Pretty JSON editor if available; otherwise a textarea
    formfield_overrides = {
        models.JSONField: {"widget": _JSONWidget},
    }


@admin.register(SupplierProduct)
class SupplierProductAdmin(admin.ModelAdmin):
    list_display = (
        "provider_account",
        "external_id",
        "variant",
        "is_active",
        "last_synced_at",
    )
    list_filter = ("provider_account", "is_active")
    search_fields = ("external_id", "variant__sku", "variant__product__title")


@admin.register(ProviderSyncLog)
class ProviderSyncLogAdmin(admin.ModelAdmin):
    list_display = (
        "provider_account",
        "status",
        "started_at",
        "finished_at",
        "duration_ms",
    )
    list_filter = ("status", "provider_account")
    date_hierarchy = "started_at"
    search_fields = ("provider_account__code", "first_error")
