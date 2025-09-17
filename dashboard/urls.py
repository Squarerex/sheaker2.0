from __future__ import annotations

from django.urls import path

from . import views_home as home
from . import views_products as views

app_name = "dashboard"

urlpatterns = [
    # Role-aware landing
    path("", home.dashboard_home, name="home"),
    path("admin/", home.home_admin, name="home_admin"),
    path("editor/", home.home_editor, name="home_editor"),
    path("marketer/", home.home_marketer, name="home_marketer"),
    path("vendor/", home.home_vendor, name="home_vendor"),
    # path("", views.dashboard_home, name="home"),
    path("products/", views.product_list, name="product_list"),
    path("products/new/", views.product_create, name="product_create"),
    path("products/<int:pk>/edit/", views.product_edit, name="product_edit"),
]
