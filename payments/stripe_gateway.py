# payments/stripe_gateway.py
from __future__ import annotations

from decimal import Decimal
from typing import Any

import stripe
from django.conf import settings

stripe.api_key = settings.STRIPE_SECRET_KEY


def to_stripe_amount_gbp(major: Decimal) -> int:
    # GBP has 2 decimals
    return int((Decimal(major) * 100).quantize(Decimal("1")))


def create_checkout_session(
    *,
    order_id: int,
    amount_gbp: Decimal,
    success_url: str,
    cancel_url: str,
    customer_email: str | None,
    metadata: dict[str, Any],
) -> stripe.checkout.Session:
    session = stripe.checkout.Session.create(
        mode="payment",
        payment_method_types=["card"],
        line_items=[
            {
                "price_data": {
                    "currency": "GBP",
                    "product_data": {"name": f"Order #{order_id}"},
                    "unit_amount": to_stripe_amount_gbp(amount_gbp),
                },
                "quantity": 1,
            }
        ],
        success_url=success_url,
        cancel_url=cancel_url,
        customer_email=customer_email or "",  # Fix: Stripe expects str, not str | None
        metadata=metadata,
    )
    return session