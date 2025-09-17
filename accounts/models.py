from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class UserType(models.TextChoices):
        ADMIN = "admin", "Admin"
        EDITOR = "editor", "Editor"
        MARKETER = "marketer", "Marketer"
        VENDOR = "vendor", "Vendor"
        CUSTOMER = "customer", "Customer"

    user_type = models.CharField(
        max_length=20, choices=UserType.choices, default=UserType.CUSTOMER
    )
    phone = models.CharField(max_length=32, blank=True)  # <-- ADD THIS

    def has_role(self, *roles: str) -> bool:
        roles_norm = {r.strip().lower() for r in roles if r and str(r).strip()}
        if not roles_norm:
            return False
        if self.is_superuser:
            return True
        if (self.user_type or "").lower() in roles_norm:
            return True
        if "staff" in roles_norm and self.is_staff:
            return True
        user_groups = {g.name.lower() for g in self.groups.all()}
        return not roles_norm.isdisjoint(user_groups)
