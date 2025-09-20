from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # Auth
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls", namespace="accounts")),
    path("dashboard/", include("dashboard.urls", namespace="dashboard")),
    path("", include("storefront.urls", namespace="storefront")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
