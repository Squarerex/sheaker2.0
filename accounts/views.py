from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView as DjangoLoginView
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse

from .forms import ProfileForm, RegisterForm
from .models import User

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
