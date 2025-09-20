from django.urls import path

from . import views_cart, views_catalog

app_name = "storefront"

urlpatterns = [
    path("", views_catalog.home, name="home"),
    path("c/<slug:slug>/", views_catalog.category_listing, name="category"),
    path("p/<slug:slug>/", views_catalog.product_detail, name="product_detail"),
    # Cart
    path("cart/", views_cart.cart_detail, name="cart_detail"),
    path("cart/add/", views_cart.cart_add, name="cart_add"),
    path("cart/update/", views_cart.cart_update, name="cart_update"),
    path("cart/remove/", views_cart.cart_remove, name="cart_remove"),
    path("cart/mini/", views_cart.cart_mini, name="cart_mini"),
    path("cart/checkout/start/", views_cart.checkout_start, name="checkout_start"),
]
