# orders/urls.py (or add to storefront)
from django.urls import path

from . import views_checkout

app_name = "orders"
urlpatterns = [
    path("checkout/review/", views_checkout.checkout_review, name="checkout_review"),
    path("checkout/start/", views_checkout.checkout_start, name="checkout_start"),
    path("checkout/success/", views_checkout.checkout_success, name="checkout_success"),
    path("checkout/cancel/", views_checkout.checkout_cancel, name="checkout_cancel"),
]
