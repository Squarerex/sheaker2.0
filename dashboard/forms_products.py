from __future__ import annotations

import uuid
from pathlib import Path
from typing import IO

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.forms import BaseInlineFormSet, inlineformset_factory

from catalog.models import Category, Media, Product, Subcategory, Variant

# Where temp files go (create this folder; gitignore it)
TMP_DIR = getattr(settings, "TMP_IMPORT_DIR", Path(settings.BASE_DIR) / "tmp_imports")

ALLOWED_EXTS = {".json", ".csv"}


# --- Variant form: include read-only ID column ---
class VariantForm(forms.ModelForm):
    id_display = forms.IntegerField(label="ID", required=False, disabled=True)

    class Meta:
        model = Variant
        fields = (
            "id_display",
            "sku",
            "attributes",
            "price_base",
            "currency",
            "weight",
            "dims",
            "is_active",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["id_display"].initial = self.instance.pk


# --- Media form ---
class MediaForm(forms.ModelForm):
    class Meta:
        model = Media
        fields = ("kind", "image", "video", "url", "alt", "is_main", "position")


# --- Enforce a single 'main' per product in the product-level media formset ---
class BaseProductMediaFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        main_count = 0
        for form in self.forms:
            if not getattr(form, "cleaned_data", None):
                continue
            if form.cleaned_data.get("DELETE"):
                continue
            if form.cleaned_data.get("is_main"):
                main_count += 1
        if main_count > 1:
            raise ValidationError(
                "Only one media item can be marked as main for this product."
            )


# Factories you'll import in views
VariantFormSet = inlineformset_factory(
    parent_model=Product,
    model=Variant,
    form=VariantForm,
    extra=1,
    can_delete=True,
)


# ---------- Product ----------
class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = (
            "title",
            "description",
            "brand",
            "category",
            "subcategory",
            "is_active",
        )
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only active categories/subcategories
        self.fields["category"].queryset = Category.objects.filter(
            is_active=True
        ).order_by("name")
        self.fields["subcategory"].queryset = Subcategory.objects.filter(
            is_active=True
        ).order_by("category__name", "name")
        # If a category is selected, limit subcategories to that category
        cat = self.instance.category_id or self.data.get("category")
        if cat:
            self.fields["subcategory"].queryset = self.fields[
                "subcategory"
            ].queryset.filter(category_id=cat)


ProductMediaFormSet = inlineformset_factory(
    parent_model=Product,
    model=Media,
    form=MediaForm,
    formset=BaseProductMediaFormSet,
    extra=3,
    can_delete=True,
)


class BulkUploadForm(forms.Form):
    file = forms.FileField(
        label="Upload file",
        help_text="JSON or CSV. CSV must include: title, sku, price.",
    )
    update_existing = forms.BooleanField(
        required=False,
        initial=True,
        label="Upsert existing products/variants (uncheck for Create-only)",
    )

    def clean_file(self):
        f: IO[bytes] = self.cleaned_data["file"]
        name = getattr(f, "name", "")
        ext = Path(name).suffix.lower()
        if ext not in ALLOWED_EXTS:
            raise ValidationError("Only .json or .csv files are allowed.")
        # generous cap: 1GB
        if f.size and f.size > 1_000_000_000:
            raise ValidationError("File too large (limit ~1GB).")
        return f

    def save_temp(self) -> tuple[Path, str]:
        """
        Persist the uploaded file to tmp_imports and return (path, token).
        """
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        f: IO[bytes] = self.cleaned_data["file"]
        name = getattr(f, "name", "upload")
        ext = Path(name).suffix.lower()
        token = f"{uuid.uuid4().hex}{ext}"
        dest = TMP_DIR / token
        with dest.open("wb") as out:
            for chunk in f.chunks():  # type: ignore[attr-defined]
                out.write(chunk)
        return dest, token
