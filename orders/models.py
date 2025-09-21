from django.db import models


class Order(models.Model):
    # ...existing fields like user, total_amount, currency, status, etc.
    payment_status = models.CharField(
        max_length=20, default="unpaid"
    )  # unpaid|paid|failed|canceled
    stripe_checkout_session_id = models.CharField(max_length=255, blank=True)
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True)


class OrderItem(models.Model):
    order = models.ForeignKey("Order", on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey("catalog.Variant", on_delete=models.PROTECT)

    quantity = models.PositiveIntegerField(default=1)
    # store authoritative GBP amounts (2dp)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    total_price = models.DecimalField(max_digits=12, decimal_places=2)

    # helpful snapshots to keep history even if product/variant later changes
    title_snapshot = models.CharField(max_length=255, blank=True)
    sku_snapshot = models.CharField(max_length=64, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:
        return f"OrderItem(order={self.order_id}, variant={self.variant_id}, qty={self.quantity})"
