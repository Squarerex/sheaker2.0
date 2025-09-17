from celery import shared_task
from django.core.management import call_command


@shared_task
def cleanup_tmp_imports_task(hours: int = 24) -> None:
    # Runs your management command
    call_command("cleanup_tmp_imports", "--hours", str(hours))
