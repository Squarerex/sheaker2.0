from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from .models import User

@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Role", {"fields": ("user_type",)}),
    )
    list_display = ("username", "email", "is_staff", "is_superuser", "user_type")
    list_filter = ("is_staff", "is_superuser", "user_type")
