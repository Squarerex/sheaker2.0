from __future__ import annotations

from django.urls import path

from . import views_home as home
from . import views_products as views
from . import views_providers, views_uploads
from .views_uploads import cj_minimal_extract

app_name = "dashboard"

urlpatterns = [
    # Role-aware landing
    path("", home.dashboard_home, name="home"),
    path("admin/", home.admin_dashboard, name="admin_dashboard"),
    path("editor/", home.editor_dashboard, name="editor_dashboard"),
    path("marketer/", home.marketer_dashboard, name="marketer_dashboard"),
    path("vendor/", home.vendor_dashboard, name="vendor_dashboard"),
    path("customer/", home.customer_dashboard, name="customer_dashboard"),
    # Products CRUD + bulk upload
    path("products/", views.product_list, name="product_list"),
    path("products/new/", views.product_create, name="product_create"),
    path("products/<int:pk>/edit/", views.product_edit, name="product_edit"),
    path("products/upload/", views_uploads.product_upload, name="product_upload"),
    path(
        "products/upload/preview/",
        views_uploads.product_upload_preview,
        name="product_upload_preview",
    ),
    path(
        "products/upload/commit/",
        views_uploads.product_upload_commit,
        name="product_upload_commit",
    ),
    path(
        "products/upload/sample.json",
        views_uploads.product_upload_sample_json,
        name="product_upload_sample_json",
    ),
    path(
        "products/upload/sample.csv",
        views_uploads.product_upload_sample_csv,
        name="product_upload_sample_csv",
    ),
    path(
        "products/upload/errors.json",
        views_uploads.product_upload_errors_json,
        name="product_upload_errors_json",
    ),
    path(
        "providers/download/<str:token>/",
        views_providers.providers_download,
        name="providers_download",
    ),
    path("tools/cj-extract/", cj_minimal_extract, name="cj_minimal_extract"),
    # Providers: status, ping, sync now, targeted sync form
    path("providers/status/", views_providers.providers_status, name="providers_status"),
    path(
        "providers/<slug:code>/ping/",
        views_providers.provider_ping,
        name="provider_ping",
    ),
    path(
        "providers/<slug:code>/sync-now/",
        views_providers.provider_sync_now,
        name="provider_sync_now",
    ),
    path(
        "providers/sync/",
        views_providers.providers_sync_form,
        name="providers_sync_form",
    ),
]
