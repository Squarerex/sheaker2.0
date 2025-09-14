from functools import wraps
from typing import Iterable
from urllib.parse import urlencode
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, resolve_url
from django.conf import settings

def role_required(roles: Iterable[str], *, superuser_always_ok: bool = True, staff_as_admin: bool = True):
    allowed = set(roles)

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            user = request.user

            if not user.is_authenticated:
                login_url = resolve_url(getattr(settings, "LOGIN_URL", "login"))
                params = urlencode({"next": request.get_full_path()})
                return redirect(f"{login_url}?{params}")

            if superuser_always_ok and getattr(user, "is_superuser", False):
                return view_func(request, *args, **kwargs)

            if staff_as_admin and "admin" in allowed and getattr(user, "is_staff", False):
                return view_func(request, *args, **kwargs)

            if getattr(user, "user_type", None) in allowed:
                return view_func(request, *args, **kwargs)

            return HttpResponseForbidden("You do not have permission to view this page.")
        return _wrapped
    return decorator
