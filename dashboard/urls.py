from __future__ import annotations

from django.urls import path

from . import views_home as home
from . import views_products as views
from . import views_uploads

app_name = "dashboard"

urlpatterns = [
    # Role-aware landing
    # path("", home.dashboard_home, name="home"),
    path("admin/", home.admin_dashboard, name="admin_dashboard"),
    path("editor/", home.editor_dashboard, name="editor_dashboard"),
    path("marketer/", home.marketer_dashboard, name="marketer_dashboard"),
    path("vendor/", home.vendor_dashboard, name="vendor_dashboard"),
    path("customer/", home.customer_dashboard, name="customer_dashboard"),
    # path("", views.dashboard_home, name="home"),
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
]
