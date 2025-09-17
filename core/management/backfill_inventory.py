# core/management/commands/backfill_inventory.py
from django.core.management.base import BaseCommand

from catalog.models import Inventory, Variant


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        created = 0
        for v in Variant.objects.all():
            Inventory.objects.get_or_create(variant=v)
            created += 1
        self.stdout.write(f"Ensured inventory rows for {created} variants.")
