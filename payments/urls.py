# payments/urls.py
from django.urls import path

from .webhooks import stripe_webhook

app_name = "payments"
urlpatterns = [
    path("stripe/webhook/", stripe_webhook, name="stripe_webhook"),
]
