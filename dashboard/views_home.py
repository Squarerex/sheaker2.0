# dashboard/views_home.py
from __future__ import annotations

from typing import Optional

from django.contrib.auth.views import redirect_to_login
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from catalog.models import (
    Inventory,
    Media,
    Product,
    Variant,
)  # quick stats for editor/admin

from .authz import role_required  # your decorator from authz.py

# If a user belongs to multiple groups, we pick the first match in this order.
ROLE_PRIORITY = ["admin", "editor", "marketer", "vendor", "customer"]


def _user_primary_role(request: HttpRequest) -> Optional[str]:
    """
    Return the user's primary role by priority, or None if they have no role.
    Superusers -> 'admin'. (Optional: treat staff-without-group as 'editor'.)
    """
    user = request.user
    if not user.is_authenticated:
        return None

    if user.is_superuser:
        return "admin"

    # Exact group name match (case-insensitive)
    user_groups = {g.name.lower() for g in user.groups.all()}
    for role in ROLE_PRIORITY:
        if role in user_groups:
            return role

    # Uncomment if you want staff-without-group to land on editor dashboard:
    # if user.is_staff:
    #     return "editor"

    return None


def dashboard_home(request: HttpRequest) -> HttpResponse:
    """
    GET /dashboard/
    - If not logged in → send to login
    - If logged in → detect role and redirect to their dashboard URL
    - If no role → render a neutral explainer page (you can customize template)
    """
    if not request.user.is_authenticated:
        return redirect_to_login(next=request.get_full_path())

    role = _user_primary_role(request)
    if role == "admin":
        return redirect("dashboard:admin_dashboard")
    if role == "editor":
        return redirect("dashboard:editor_dashboard")
    if role == "marketer":
        return redirect("dashboard:marketer_dashboard")
    if role == "vendor":
        return redirect("dashboard:vendor_dashboard")
    if role == "customer":
        return redirect("dashboard:customer_dashboard")

    # No role: show a simple page (create templates/dashboard/no_role.html or tweak as you prefer)
    return render(request, "dashboard/no_role.html", {"role": None})


@role_required(["admin"])
def admin_dashboard(request: HttpRequest) -> HttpResponse:
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
    return render(request, "dashboard/admin_dashboard.html", ctx)


@role_required(["editor"])
def editor_dashboard(request: HttpRequest) -> HttpResponse:
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
    return render(request, "dashboard/editor_dashboard.html", ctx)


@role_required(["marketer"])
def marketer_dashboard(request: HttpRequest) -> HttpResponse:
    """
    /dashboard/marketer/ — visible to marketer group.
    """
    return render(request, "dashboard/marketer_dashboard.html", {"role": "marketer"})


@role_required(["vendor"])
def vendor_dashboard(request: HttpRequest) -> HttpResponse:
    """
    /dashboard/vendor/ — visible to vendor group.
    """
    return render(request, "dashboard/vendor_dashboard.html", {"role": "vendor"})


@role_required(["customer"])
def customer_dashboard(request: HttpRequest) -> HttpResponse:
    """
    /dashboard/customer/ — visible to customer group.
    """
    return render(
        request, "dashboard/customers/customers_dashboard.html", {"role": "customer"}
    )
