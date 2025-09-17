from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseInlineFormSet, inlineformset_factory

from catalog.models import Category, Media, Product, Subcategory, Variant


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
