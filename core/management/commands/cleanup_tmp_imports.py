import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Delete tmp_imports files older than N hours (default 24h)."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=24)

    def handle(self, *args, **opts):
        root = Path(
            getattr(settings, "TMP_IMPORT_DIR", Path(settings.BASE_DIR) / "tmp_imports")
        )
        if not root.exists():
            self.stdout.write("No tmp_imports dir.")
            return
        cutoff = time.time() - (opts["hours"] * 3600)
        removed = 0
        for p in root.iterdir():
            if p.is_file() and p.stat().st_mtime < cutoff:
                p.unlink(missing_ok=True)
                removed += 1
        self.stdout.write(f"Removed {removed} files.")
