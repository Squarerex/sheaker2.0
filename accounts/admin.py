# accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    # Show user_type in the edit screen
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (_("Personal info"), {"fields": ("first_name", "last_name", "email")}),
        (
            _("Roles & permissions"),
            {
                "fields": (
                    "user_type",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )

    # Show user_type when adding a new user
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "password1",
                    "password2",
                    "email",
                    "first_name",
                    "last_name",
                    "user_type",
                ),
            },
        ),
    )

    list_display = (
        "username",
        "email",
        "user_type",
        "is_staff",
        "is_superuser",
        "last_login",
    )
    list_filter = ("user_type", "is_staff", "is_superuser", "is_active", "groups")
    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("username",)

    # Handy bulk actions to set roles and trigger your sync signal
    actions = [
        "make_admin",
        "make_editor",
        "make_marketer",
        "make_vendor",
        "make_customer",
    ]

    def _set_role(self, request, queryset, role: str):
        n = 0
        for u in queryset:
            u.user_type = role
            u.save()  # triggers post_save signal to sync Groups
            n += 1
        self.message_user(request, f"Updated {n} user(s) to role “{role}”.")

    def make_admin(self, request, queryset):
        self._set_role(request, queryset, "admin")

    make_admin.short_description = "Set role: admin"

    def make_editor(self, request, queryset):
        self._set_role(request, queryset, "editor")

    make_editor.short_description = "Set role: editor"

    def make_marketer(self, request, queryset):
        self._set_role(request, queryset, "marketer")

    make_marketer.short_description = "Set role: marketer"

    def make_vendor(self, request, queryset):
        self._set_role(request, queryset, "vendor")

    make_vendor.short_description = "Set role: vendor"

    def make_customer(self, request, queryset):
        self._set_role(request, queryset, "customer")

    make_customer.short_description = "Set role: customer"
