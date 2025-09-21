# payments/webhooks.py
from __future__ import annotations

import stripe
from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt

from orders.models import Order


@csrf_exempt
def stripe_webhook(request: HttpRequest) -> HttpResponse:
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=settings.STRIPE_WEBHOOK_SECRET,
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        return HttpResponseBadRequest("Invalid payload or signature")

    if event["type"] in ("checkout.session.completed",):
        session = event["data"]["object"]
        order_id = session.get("metadata", {}).get("order_id")
        if order_id:
            try:
                order = Order.objects.get(pk=order_id)
            except Order.DoesNotExist:
                return HttpResponse(status=200)  # Ignore silently
            order.payment_status = "paid"
            order.stripe_checkout_session_id = session.get("id", "")
            order.stripe_payment_intent_id = session.get("payment_intent", "")
            order.status = getattr(order, "status", "paid")  # if you track a separate order status
            order.save(
                update_fields=[
                    "payment_status",
                    "stripe_checkout_session_id",
                    "stripe_payment_intent_id",
                    "status",
                ]
            )
    return HttpResponse(status=200)
