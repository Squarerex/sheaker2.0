# dashboard/views_home.py
from __future__ import annotations

from django.contrib.auth.views import redirect_to_login
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from catalog.models import (
    Inventory,
    Media,
    Product,
    Variant,
)  # for quick stats on admin/editor

from .authz import role_required  # your decorator from authz.py

# Role priority: if a user has multiple groups, we pick the first that appears here.
ROLE_PRIORITY = ["admin", "editor", "marketer", "vendor"]


def _user_primary_role(request: HttpRequest) -> str | None:
    """
    Return the user's primary role by priority, or None if they have no role.
    Superusers are treated as 'admin'. Staff (no group) treated as 'editor'.
    """
    user = request.user
    if not user.is_authenticated:
        return None

    if user.is_superuser:
        return "admin"

    # Exact group name match, case-insensitive
    user_groups = {g.name.lower() for g in user.groups.all()}
    for role in ROLE_PRIORITY:
        if role in user_groups:
            return role

    # Optional: treat staff without a group as editors
    if user.is_staff:
        return "editor"

    return None


def dashboard_home(request: HttpRequest) -> HttpResponse:
    """
    GET /dashboard/
    - If not logged in → send to login
    - If logged in → detect role and redirect to their dashboard URL
    - If no role → show a neutral page explaining they need a role
    """
    if not request.user.is_authenticated:
        return redirect_to_login(next=request.get_full_path())

    role = _user_primary_role(request)
    if role == "admin":
        return redirect("dashboard:home_admin")
    if role == "editor":
        return redirect("dashboard:home_editor")
    if role == "marketer":
        return redirect("dashboard:home_marketer")
    if role == "vendor":
        return redirect("dashboard:home_vendor")

    # No role assigned: show a neutral page
    return render(request, "dashboard/home_neutral.html")


@role_required(["admin"])
def home_admin(request: HttpRequest) -> HttpResponse:
    """
    /dashboard/admin/ — visible to admin group (and superusers).
    Minimal stats to prove it's wired. Extend later with widgets.
    """
    ctx = {
        "role": "admin",
        "counts": {
            "products": Product.objects.count(),
            "variants": Variant.objects.count(),
            "media": Media.objects.count(),
            "inventory": Inventory.objects.count(),
        },
    }
    return render(request, "dashboard/home_admin.html", ctx)


@role_required(["editor"])
def home_editor(request: HttpRequest) -> HttpResponse:
    """
    /dashboard/editor/ — visible to editor group.
    """
    ctx = {
        "role": "editor",
        "counts": {
            "products": Product.objects.count(),
            "variants": Variant.objects.count(),
        },
    }
    return render(request, "dashboard/home_editor.html", ctx)


@role_required(["marketer"])
def home_marketer(request: HttpRequest) -> HttpResponse:
    """
    /dashboard/marketer/ — visible to marketer group.
    Keep Phase 1 simple; add KPIs later.
    """
    return render(request, "dashboard/home_marketer.html", {"role": "marketer"})


@role_required(["vendor"])
def home_vendor(request: HttpRequest) -> HttpResponse:
    """
    /dashboard/vendor/ — visible to vendor group.
    Phase 2 will scope to vendor-owned products.
    """
    return render(request, "dashboard/home_vendor.html", {"role": "vendor"})
