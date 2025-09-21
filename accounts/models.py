from __future__ import annotations

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models

_phone_validator = RegexValidator(
    regex=r"^\+?[1-9]\d{7,14}$",  # simple E.164-ish
    message="Enter a valid phone number (e.g. +2348012345678).",
)


class User(AbstractUser):
    class UserType(models.TextChoices):
        ADMIN = "admin", "Admin"
        EDITOR = "editor", "Editor"
        MARKETER = "marketer", "Marketer"
        VENDOR = "vendor", "Vendor"
        CUSTOMER = "customer", "Customer"

    user_type = models.CharField(max_length=20, choices=UserType.choices, default=UserType.CUSTOMER)
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


class Address(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="addresses"
    )
    full_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, validators=[_phone_validator])
    line1 = models.CharField(max_length=200)
    line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=120)
    state = models.CharField(max_length=120, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=2, default="NG")  # ISO 3166-1 alpha-2
    is_default = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_default", "-updated_at"]

    def __str__(self) -> str:
        return f"{self.full_name}, {self.line1}, {self.city}"


class Wishlist(models.Model):
    """
    Wishlist model to store user's favorite products.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wishlist"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounts_wishlist"
        verbose_name = "Wishlist"
        verbose_name_plural = "Wishlists"

    def __str__(self):
        return f"{self.user.username}'s Wishlist"

    @property
    def item_count(self):
        """Get total number of items in wishlist."""
        return self.items.count()

    @property
    def total_value(self):
        """Calculate total value of all items in wishlist (using cheapest variant price)."""
        total = 0
        for item in self.items.select_related("product"):
            # Get the cheapest variant price for this product
            cheapest_variant = (
                item.product.variants.filter(is_active=True).order_by("price_base").first()
            )
            if cheapest_variant:
                total += float(cheapest_variant.price_base)
        return total

    def clear(self):
        """Remove all items from wishlist."""
        self.items.all().delete()


class WishlistItem(models.Model):
    """
    Individual items in a user's wishlist.
    """

    wishlist = models.ForeignKey(Wishlist, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.CASCADE, related_name="wishlist_items"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, null=True, help_text="Personal notes about this product")

    class Meta:
        db_table = "accounts_wishlist_item"
        verbose_name = "Wishlist Item"
        verbose_name_plural = "Wishlist Items"
        unique_together = ("wishlist", "product")  # Prevent duplicate items
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.product.title} in {self.wishlist.user.username}'s wishlist"

    @property
    def current_price(self):
        """Get current price (cheapest active variant)."""
        cheapest_variant = (
            self.product.variants.filter(is_active=True).order_by("price_base").first()
        )
        return cheapest_variant.price_base if cheapest_variant else 0

    @property
    def is_available(self):
        """Check if the product has any available variants."""
        return self.product.is_active and self.product.variants.filter(is_active=True).exists()

    @property
    def in_stock(self):
        """Check if any variant is in stock."""
        for variant in self.product.variants.filter(is_active=True):
            if hasattr(variant, "inventory") and variant.inventory.in_stock:
                return True
        return False
