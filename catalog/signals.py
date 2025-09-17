# catalog/signals.py
from __future__ import annotations

from django.db.models.signals import pre_save
from django.dispatch import receiver

from .models import Product
from .utils import slugify_unique


@receiver(pre_save, sender=Product)
def product_auto_slug(sender, instance: Product, **kwargs) -> None:
    if not instance.slug:
        instance.slug = slugify_unique(Product, instance.title)
