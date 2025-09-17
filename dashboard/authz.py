# dashboard/authz.py
from __future__ import annotations

from functools import wraps
from typing import Iterable, Union

from django.contrib.auth.views import redirect_to_login
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden

RolesArg = Union[str, Iterable[str]]


def _normalize_roles(roles: RolesArg) -> set[str]:
    if isinstance(roles, str):
        roles_iter = [roles]
    else:
        roles_iter = roles
    return {r.strip().lower() for r in roles_iter if r and str(r).strip()}


def user_has_any_role(user, roles: set[str]) -> bool:
    if not (user and user.is_authenticated and user.is_active):
        return False
    if getattr(user, "is_superuser", False):
        return True
    # optional pseudo-role: "staff" matches Django staff users
    if "staff" in roles and getattr(user, "is_staff", False):
        return True
    user_groups = {g.name.lower() for g in user.groups.all()}
    return not roles.isdisjoint(user_groups)


def role_required(roles: RolesArg):
    """
    Usage:
      @role_required("admin")
      @role_required(["admin", "editor"])
      @role_required({"admin", "editor", "marketer"})
      @role_required(["staff"])  # optional: allow any staff user
    """
    normalized = _normalize_roles(roles)

    def decorator(viewfunc):
        @wraps(viewfunc)
        def _wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            user = request.user
            if not (user and user.is_authenticated):
                # redirect to login if anonymous
                return redirect_to_login(next=request.get_full_path())
            if user_has_any_role(user, normalized):
                return viewfunc(request, *args, **kwargs)
            return HttpResponseForbidden("You do not have permission to access this.")

        return _wrapped

    return decorator
