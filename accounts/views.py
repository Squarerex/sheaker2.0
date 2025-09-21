from __future__ import annotations

import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView as DjangoLoginView
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.views.decorators.http import require_POST

from catalog.models import Product

from .forms import ProfileForm, RegisterForm
from .models import User, Wishlist, WishlistItem

# -------- Role → destination helpers --------

ROLE_ORDER = ("admin", "editor", "marketer", "vendor", "customer")

# Try namespaced route first (dashboard:xxx), then global (xxx)
DASHBOARD_URLS = {
    "admin": ("dashboard:admin_dashboard", "admin_dashboard"),
    "editor": ("dashboard:editor_dashboard", "editor_dashboard"),
    "marketer": ("dashboard:marketer_dashboard", "marketer_dashboard"),
    "vendor": ("dashboard:vendor_dashboard", "vendor_dashboard"),
    "customer": ("dashboard:customer_dashboard", "customer_dashboard"),
}


def _primary_role(user) -> str | None:
    """Return the user's primary role, or None if they have none of the known groups."""
    if getattr(user, "is_superuser", False) or user.groups.filter(name="admin").exists():
        return "admin"
    for r in ROLE_ORDER[1:]:
        if user.groups.filter(name=r).exists():
            return r
    return None


def _reverse_first(*names: str) -> str | None:
    for name in names:
        try:
            return reverse(name)
        except NoReverseMatch:
            continue
    return None


def _storefront_url() -> str:
    # Try names you might have; fall back to site root
    url = _reverse_first("storefront:home", "storefront_home")
    return url or "/"


def _dashboard_url_for(user) -> str:
    """
    Map role -> dashboard URL (your names), else storefront.
    """
    role = _primary_role(user)
    if not role:
        return _storefront_url()

    target = _reverse_first(*DASHBOARD_URLS.get(role, ()))
    return target or _storefront_url()


# -------- Views --------


class RoleLoginView(DjangoLoginView):
    """
    Login that:
      • honors ?next=... if present
      • otherwise sends user to the correct dashboard by role
    """

    redirect_authenticated_user = True

    def get_success_url(self):
        nxt = self.get_redirect_url()
        if nxt:
            return nxt
        return _dashboard_url_for(self.request.user)


@login_required
def post_login_redirect(request: HttpRequest) -> HttpResponse:
    """
    Generic router you can link to from anywhere after auth.
    """
    return redirect(_dashboard_url_for(request.user))


def register(request: HttpRequest) -> HttpResponse:
    """
    Public signup -> logs in -> routes by role/customer → dashboard or storefront.
    By default we flag new users as 'customer' type (adjust as needed).
    """
    if not getattr(settings, "ALLOW_PUBLIC_SIGNUP", True):
        messages.error(request, "New account registration is currently disabled.")
        return redirect("accounts:login")

    if request.user.is_authenticated:
        # Already logged in: just route them
        return redirect(_dashboard_url_for(request.user))

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user: User = form.save(commit=False)
            # if your User model has user_type, keep this; otherwise drop it
            setattr(user, "user_type", getattr(user, "user_type", "customer"))
            user.email = form.cleaned_data.get("email", "").strip()
            if hasattr(user, "phone"):
                user.phone = form.cleaned_data.get("phone", "").strip()
            user.save()  # if you have a signal attaching 'customer' group, it will run here

            raw_password = form.cleaned_data["password1"]
            auth_user = authenticate(request, username=user.username, password=raw_password)
            if auth_user is not None:
                login(request, auth_user)

            messages.success(request, "Account created. Welcome!")
            next_url = request.GET.get("next") or _dashboard_url_for(request.user)
            return redirect(next_url)

        messages.error(request, "Please fix the errors below.")
    else:
        form = RegisterForm()

    return render(request, "registration/register.html", {"form": form})


@login_required
def profile(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated.")
            return redirect("accounts:profile")
        messages.error(request, "Please fix the errors below.")
    else:
        form = ProfileForm(instance=request.user)
    return render(request, "accounts/profile.html", {"form": form})


@login_required
def customer_wishlist(request):
    """Display customer's wishlist with pagination and sorting options."""

    # Get or create wishlist for the user
    wishlist, created = Wishlist.objects.get_or_create(user=request.user)

    # Get sorting parameter
    sort_by = request.GET.get("sort", "date_added")

    # Define sorting options
    sort_options = {
        "date_added": "-created_at",
        "name": "product__title",
        "price_low": "product__variants__price_base",
        "price_high": "-product__variants__price_base",
    }

    order_by = sort_options.get(sort_by, "-created_at")

    # Get wishlist items with related product data
    wishlist_items = (
        WishlistItem.objects.filter(wishlist=wishlist)
        .select_related("product")
        .prefetch_related("product__variants", "product__media")
        .order_by(order_by)
    )

    # Calculate statistics
    total_items = wishlist_items.count()
    in_stock_count = sum(1 for item in wishlist_items if item.in_stock)

    # Calculate total value
    total_value = wishlist.total_value

    # Pagination
    paginator = Paginator(wishlist_items, 12)  # Show 12 items per page
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "wishlist": wishlist,
        "wishlist_items": page_obj,
        "total_items": total_items,
        "in_stock_count": in_stock_count,
        "total_value": f"${total_value:.2f}" if total_value > 0 else "$0.00",
        "sort_by": sort_by,
        "wishlist_count": total_items,  # For header display
    }

    return render(request, "accounts/wishlist.html", context)


@login_required
@require_POST
def add_to_wishlist(request):
    """Add a product to user's wishlist via AJAX."""

    try:
        data = json.loads(request.body)
        product_id = data.get("product_id")

        if not product_id:
            return JsonResponse({"success": False, "message": "Product ID is required"})

        product = get_object_or_404(Product, id=product_id, is_active=True)

        # Get or create wishlist
        wishlist, created = Wishlist.objects.get_or_create(user=request.user)

        # Check if item already exists
        wishlist_item, item_created = WishlistItem.objects.get_or_create(
            wishlist=wishlist, product=product
        )

        if item_created:
            message = f"{product.title} has been added to your wishlist!"
            success = True
        else:
            # Item already exists, remove it (toggle behavior)
            wishlist_item.delete()
            message = f"{product.title} has been removed from your wishlist!"
            success = True

        # Get updated count
        wishlist_count = WishlistItem.objects.filter(wishlist=wishlist).count()

        return JsonResponse(
            {"success": success, "message": message, "count": wishlist_count, "added": item_created}
        )

    except Product.DoesNotExist:
        return JsonResponse({"success": False, "message": "Product not found"})
    except Exception:
        return JsonResponse(
            {"success": False, "message": "An error occurred while updating your wishlist"}
        )


@login_required
@require_POST
def remove_from_wishlist(request):
    """Remove a product from user's wishlist via AJAX."""

    try:
        data = json.loads(request.body)
        product_id = data.get("product_id")

        if not product_id:
            return JsonResponse({"success": False, "message": "Product ID is required"})

        product = get_object_or_404(Product, id=product_id)
        wishlist = get_object_or_404(Wishlist, user=request.user)

        # Remove the item
        removed_count = WishlistItem.objects.filter(wishlist=wishlist, product=product).delete()[0]

        if removed_count > 0:
            message = f"{product.title} has been removed from your wishlist!"
            success = True
        else:
            message = "Item was not found in your wishlist"
            success = False

        # Get updated count
        wishlist_count = WishlistItem.objects.filter(wishlist=wishlist).count()

        return JsonResponse({"success": success, "message": message, "count": wishlist_count})

    except (Product.DoesNotExist, Wishlist.DoesNotExist):
        return JsonResponse({"success": False, "message": "Product or wishlist not found"})
    except Exception:
        return JsonResponse(
            {"success": False, "message": "An error occurred while removing the item"}
        )


@login_required
def wishlist_count(request):
    """Get current wishlist count for AJAX requests."""

    try:
        wishlist = Wishlist.objects.get(user=request.user)
        count = WishlistItem.objects.filter(wishlist=wishlist).count()
    except Wishlist.DoesNotExist:
        count = 0

    return JsonResponse({"count": count})


@login_required
@require_POST
def clear_wishlist(request):
    """Clear all items from user's wishlist."""

    try:
        wishlist = Wishlist.objects.get(user=request.user)
        deleted_count = WishlistItem.objects.filter(wishlist=wishlist).delete()[0]

        messages.success(request, f"Removed {deleted_count} items from your wishlist!")

        return JsonResponse(
            {
                "success": True,
                "message": f"Removed {deleted_count} items from your wishlist!",
                "count": 0,
            }
        )

    except Wishlist.DoesNotExist:
        return JsonResponse({"success": False, "message": "Wishlist not found"})
    except Exception:
        return JsonResponse(
            {"success": False, "message": "An error occurred while clearing your wishlist"}
        )


# Context processor to add wishlist count to all templates
def wishlist_context(request):
    """Context processor to add wishlist count to all templates."""

    wishlist_count = 0

    if request.user.is_authenticated:
        try:
            wishlist = Wishlist.objects.get(user=request.user)
            wishlist_count = WishlistItem.objects.filter(wishlist=wishlist).count()
        except Wishlist.DoesNotExist:
            wishlist_count = 0

    return {"wishlist_count": wishlist_count}
