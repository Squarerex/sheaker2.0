from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from providers.services.sync import sync_provider_products


class Command(BaseCommand):
    help = "Sync products from a provider (read-only import)."

    def add_arguments(self, parser):
        parser.add_argument("--code", required=True, help="Provider code (e.g., cj)")
        parser.add_argument("--max-pages", type=int, default=3)
        parser.add_argument("--page-size", type=int, default=50)
        parser.add_argument(
            "--dry-run", action="store_true", help="Count work but do not write to DB"
        )
        parser.add_argument(
            "--limit", type=int, default=None, help="Stop after N products (detail)"
        )
        # Common CJ list filters (pass-through)
        parser.add_argument("--category-id", default=None, help="CJ categoryId")
        parser.add_argument("--keyword", default=None, help="CJ keyword search")

    def handle(self, *args, **opts):
        code = opts["code"]
        filters = {}
        if opts.get("category_id"):
            filters["categoryId"] = opts["category_id"]
        if opts.get("keyword"):
            filters["keyword"] = opts["keyword"]

        try:
            result = sync_provider_products(
                provider_code=code,
                max_pages=opts["max_pages"],
                page_size=opts["page_size"],
                dry_run=opts["dry_run"],
                limit=opts["limit"],
                filters=filters or None,
            )
        except RuntimeError as e:
            raise CommandError(str(e)) from e
        except Exception as e:
            raise CommandError(str(e)) from e

        mode = "DRY-RUN" if opts["dry_run"] else "APPLIED"
        self.stdout.write(self.style.SUCCESS(f"[{mode}] Sync complete: {result}"))
