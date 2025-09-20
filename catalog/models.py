# catalog/models.py
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify

CURRENCY_CHOICES = [
    ("USD", "USD"),
    ("EUR", "EUR"),
    ("GBP", "GBP"),
    ("NGN", "NGN"),
]


# ---------- Base ----------
class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ---------- Taxonomy ----------
class Category(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class Subcategory(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="subcategories")
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("category", "slug"), ("category", "name")]
        ordering = ["category__name", "name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.category} › {self.name}"


# ---------- Core ----------
class Product(TimeStampedModel):
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    description = models.TextField(blank=True)
    brand = models.CharField(max_length=100, blank=True, db_index=True)
    is_recommended = models.BooleanField(default=False, db_index=True)
    is_popular = models.BooleanField(default=False, db_index=True)
    is_handpicked = models.BooleanField(default=False, db_index=True)
    home_rank = models.PositiveIntegerField(default=1000, db_index=True)

    # New: real taxonomy (FKs). Keep nullable for easy backfill; you can make non-null later.
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
        null=True,
        blank=True,
    )
    subcategory = models.ForeignKey(
        Subcategory,
        on_delete=models.PROTECT,
        related_name="products",
        null=True,
        blank=True,
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["brand"]),
            models.Index(fields=["category"]),
            models.Index(fields=["subcategory"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title

    def clean(self):
        super().clean()
        if self.subcategory and self.category and self.subcategory.category_id != self.category_id:
            raise ValidationError(
                {"subcategory": "Subcategory must belong to the selected Category."}
            )

    def save(self, *args, **kwargs):
        # Auto-slug (unique-ish) if missing
        if not self.slug and self.title:
            base = slugify(self.title)[:240] or "product"
            slug = base
            n = 1
            while Product.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                n += 1
                slug = f"{base}-{n}"
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def primary_media(self) -> Optional["Media"]:
        """Prefer the 'main' media; otherwise first by position/id."""
        main = self.media.filter(is_main=True).order_by("position", "id").first()
        return main or self.media.order_by("position", "id").first()

    @property
    def primary_image(self) -> Optional["Media"]:
        """Convenience: first image, preferring 'main' if it is an image."""
        pm = self.primary_media
        if pm and pm.kind == Media.KIND_IMAGE:
            return pm
        return self.media.filter(kind=Media.KIND_IMAGE).order_by("position", "id").first()


class Variant(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    sku = models.CharField(max_length=64, unique=True, db_index=True)
    attributes: Dict[str, Any] = models.JSONField(default=dict, blank=True)

    price_base = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="USD")

    # Use 'weight' to match dashboard forms (kilograms recommended)
    weight = models.DecimalField(max_digits=8, decimal_places=3, null=True, blank=True)
    # e.g. {"l": 10.0, "w": 5.0, "h": 3.0, "unit": "cm"}
    dims: Dict[str, Any] = models.JSONField(default=dict, blank=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["sku"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["product", "sku"]),
            models.Index(fields=["currency"]),
        ]
        ordering = ["product_id", "sku"]

    def __str__(self) -> str:
        return f"{self.product.title} · {self.sku}"


class Inventory(TimeStampedModel):
    variant = models.OneToOneField(Variant, on_delete=models.CASCADE, related_name="inventory")
    qty_available = models.PositiveIntegerField(default=0)
    safety_stock = models.PositiveIntegerField(default=0)
    warehouse = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        ordering = ["variant_id"]

    def __str__(self) -> str:
        return f"Inventory({self.variant.sku})"

    @property
    def in_stock(self) -> bool:
        return self.qty_available > self.safety_stock


class Media(models.Model):
    KIND_IMAGE = "image"
    KIND_VIDEO = "video"
    KIND_EXTERNAL = "external"
    KIND_CHOICES = [
        (KIND_IMAGE, "Image"),
        (KIND_VIDEO, "Video"),
        (KIND_EXTERNAL, "External URL"),
    ]

    # Make product nullable at the DB level; enforce consistency in clean()/save().
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="media", null=True, blank=True
    )
    # Variant-level media is allowed; product will auto-fill from variant if missing.
    variant = models.ForeignKey(
        Variant, on_delete=models.CASCADE, related_name="media", null=True, blank=True
    )

    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_IMAGE)

    # Keep file fields nullable; only one of image/video/url will be used depending on kind.
    image = models.ImageField(upload_to="catalog/images/", blank=True, null=True)
    video = models.FileField(
        upload_to="catalog/videos/",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(allowed_extensions=["mp4", "webm", "mov"])],
    )
    url = models.URLField(blank=True)

    alt = models.CharField(max_length=255, blank=True)
    is_main = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["product"],
                condition=Q(is_main=True, variant__isnull=True),
                name="unique_main_media_per_product",
            ),
            models.UniqueConstraint(
                fields=["variant"],
                condition=Q(is_main=True),
                name="unique_main_media_per_variant",
            ),
        ]

    def clean(self):
        super().clean()

        # You must attach to product-level OR variant-level gallery.
        if not self.product and not self.variant:
            raise ValidationError({"product": "Attach media to a product or to a variant."})

        # If both are set, they must be consistent.
        if self.product and self.variant and self.variant.product_id != self.product_id:
            raise ValidationError({"product": "Product must match the variant's product."})

        # Kind ↔ content presence
        if self.kind == self.KIND_IMAGE and not self.image:
            raise ValidationError({"image": "Upload an image when kind='image'."})
        if self.kind == self.KIND_VIDEO and not self.video:
            raise ValidationError({"video": "Upload a video when kind='video'."})
        if self.kind == self.KIND_EXTERNAL and not self.url:
            raise ValidationError({"url": "Provide a URL when kind='external'."})

    def save(self, *args, **kwargs):
        # Auto-fill product from variant to keep data consistent.
        if self.variant and not self.product:
            self.product = self.variant.product
        return super().save(*args, **kwargs)

    def __str__(self):
        base = f"{self.get_kind_display()} #{self.pk or 'new'}"
        return f"{base} (product={self.product_id}, variant={self.variant_id or '-'})"
