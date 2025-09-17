from __future__ import annotations

from django.contrib import admin

from .models import Category, Inventory, Media, Product, Subcategory, Variant


# -------- Inlines --------
class VariantInline(admin.TabularInline):
    model = Variant
    extra = 0
    fields = ("sku", "price_base", "currency", "is_active")
    show_change_link = True


class MediaInlineForProduct(admin.TabularInline):
    """
    Product-level media only (variant left blank). We don't expose the 'variant' FK here.
    """

    model = Media
    fk_name = "product"
    extra = 0
    fields = ("kind", "image", "video", "url", "alt", "is_main", "position")
    verbose_name = "Media (product level)"
    verbose_name_plural = "Media (product level)"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(variant__isnull=True)


class MediaInlineForVariant(admin.TabularInline):
    """
    Variant-level media only. Product is implied via the variant; we show the same fields.
    """

    model = Media
    fk_name = "variant"
    extra = 0
    fields = ("kind", "image", "video", "url", "alt", "is_main", "position")
    verbose_name = "Media (variant level)"
    verbose_name_plural = "Media (variant level)"


class InventoryInline(admin.StackedInline):
    model = Inventory
    extra = 0


# -------- ModelAdmins --------
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "brand",
        "category",
        "subcategory",
        "is_active",
        "created_at",
    )
    list_filter = ("is_active", "brand", "category", "subcategory")
    search_fields = ("title", "slug", "variants__sku", "brand")
    inlines = [VariantInline, MediaInlineForProduct]
    prepopulated_fields = {"slug": ("title",)}  # convenience; save() also auto-slugs

    # Useful for large datasets
    autocomplete_fields = ("category", "subcategory")


@admin.register(Variant)
class VariantAdmin(admin.ModelAdmin):
    list_display = ("sku", "product", "price_base", "currency", "is_active")
    list_filter = ("currency", "is_active")
    search_fields = ("sku", "product__title", "product__brand")
    inlines = [InventoryInline, MediaInlineForVariant]
    autocomplete_fields = ("product",)


@admin.register(Media)
class MediaAdmin(admin.ModelAdmin):
    list_display = ("kind", "product", "variant", "is_main", "position", "created_at")
    list_filter = ("kind", "is_main")
    search_fields = ("product__title", "variant__sku", "alt")
    autocomplete_fields = ("product", "variant")


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = ("variant", "qty_available", "safety_stock", "warehouse", "in_stock")
    list_filter = ("warehouse",)
    search_fields = ("variant__sku",)
    autocomplete_fields = ("variant",)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "slug")


@admin.register(Subcategory)
class SubcategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "slug", "is_active")
    list_filter = ("category",)
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "slug")
    autocomplete_fields = ("category",)
