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
        max_length=20,
        choices=UserType.choices,
        default=UserType.CUSTOMER,
    )

    def has_role(self, *roles: str) -> bool:
        return self.user_type in roles
