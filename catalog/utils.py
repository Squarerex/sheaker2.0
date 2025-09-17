# catalog/utils.py
from __future__ import annotations

from django.db.models import Model
from django.utils.text import slugify


def slugify_unique(model_cls: type[Model], value: str, slug_field: str = "slug") -> str:
    """
    Create a unique slug for `model_cls` from `value`, appending -2, -3, ... if needed.
    """
    base = slugify(value) or "item"
    slug = base
    i = 2
    while model_cls.objects.filter(**{slug_field: slug}).exists():
        slug = f"{base}-{i}"
        i += 1
    return slug
