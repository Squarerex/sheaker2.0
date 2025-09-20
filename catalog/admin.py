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
    """Product-level media only (variant left blank)."""

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
    """Variant-level media only."""

    model = Media
    fk_name = "variant"
    extra = 0
    fields = ("kind", "image", "video", "url", "alt", "is_main", "position")
    verbose_name = "Media (variant level)"
    verbose_name_plural = "Media (variant level)"


class InventoryInline(admin.StackedInline):
    model = Inventory
    extra = 0


# -------- Actions --------
def mark_recommended(modeladmin, request, queryset):
    queryset.update(is_recommended=True)


mark_recommended.short_description = "Mark as Recommended"


def mark_popular(modeladmin, request, queryset):
    queryset.update(is_popular=True)


mark_popular.short_description = "Mark as Most Popular"


def mark_handpicked(modeladmin, request, queryset):
    queryset.update(is_handpicked=True)


mark_handpicked.short_description = "Mark as Handpicked"


# -------- ModelAdmins --------
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "brand",
        "category",
        "subcategory",
        "is_active",
        "is_recommended",
        "is_popular",
        "is_handpicked",
        "home_rank",
        "updated_at",
    )
    list_filter = (
        "is_active",
        "brand",
        "category",
        "subcategory",
        "is_recommended",
        "is_popular",
        "is_handpicked",
    )
    list_editable = ("is_recommended", "is_popular", "is_handpicked", "home_rank")
    search_fields = ("title", "slug", "variants__sku", "brand")
    inlines = [VariantInline, MediaInlineForProduct]
    prepopulated_fields = {"slug": ("title",)}
    autocomplete_fields = ("category", "subcategory")
    list_select_related = ("category", "subcategory")
    ordering = ("home_rank", "-updated_at")
    list_per_page = 50
    actions = [mark_recommended, mark_popular, mark_handpicked]


@admin.register(Variant)
class VariantAdmin(admin.ModelAdmin):
    list_display = ("sku", "product", "price_base", "currency", "is_active")
    list_filter = ("currency", "is_active")
    search_fields = ("sku", "product__title", "product__brand")
    inlines = [InventoryInline, MediaInlineForVariant]
    autocomplete_fields = ("product",)
    list_select_related = ("product",)
    ordering = ("sku",)


@admin.register(Media)
class MediaAdmin(admin.ModelAdmin):
    list_display = ("kind", "product", "variant", "is_main", "position", "created_at")
    list_filter = ("kind", "is_main")
    search_fields = ("product__title", "variant__sku", "alt")
    autocomplete_fields = ("product", "variant")
    list_select_related = ("product", "variant")
    ordering = ("product", "variant", "position")


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    # Ensure Inventory has an `in_stock` property/method; if not, remove it.
    list_display = ("variant", "qty_available", "safety_stock", "warehouse", "in_stock")
    list_filter = ("warehouse",)
    search_fields = ("variant__sku",)
    autocomplete_fields = ("variant",)
    list_select_related = ("variant",)
    ordering = ("-qty_available",)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "slug")
    ordering = ("name",)


@admin.register(Subcategory)
class SubcategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "slug", "is_active")
    list_filter = ("category",)
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "slug", "category__name")
    autocomplete_fields = ("category",)
    list_select_related = ("category",)
    ordering = ("category__name", "name")
