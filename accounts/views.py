from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.debug import sensitive_post_parameters

from .forms import ProfileForm, RegisterForm
from .models import User


@sensitive_post_parameters("password1", "password2")
def register(request: HttpRequest) -> HttpResponse:
    """
    Public sign-up. Creates a `customer` by default.
    Respects settings.ALLOW_PUBLIC_SIGNUP (default True).
    """
    if not getattr(settings, "ALLOW_PUBLIC_SIGNUP", True):
        messages.error(request, "New account registration is currently disabled.")
        return redirect("accounts:login")

    if request.user.is_authenticated:
        return redirect("dashboard:home")

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user: User = form.save(commit=False)
            user.user_type = "customer"
            user.email = form.cleaned_data["email"].strip()
            user.phone = form.cleaned_data.get("phone", "").strip()
            user.save()  # triggers your post_save signal to sync Groups

            # Auto-login
            raw_password = form.cleaned_data["password1"]
            auth_user = authenticate(
                request, username=user.username, password=raw_password
            )
            if auth_user is not None:
                login(request, auth_user)

            messages.success(request, "Account created. Welcome!")
            next_url = request.GET.get("next") or reverse("dashboard:home")
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
