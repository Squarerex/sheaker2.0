import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE", os.getenv("DJANGO_SETTINGS_MODULE", "core.settings.dev")
)

app = Celery("core")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


app.conf.beat_schedule = {
    "cleanup-imports-daily": {
        "task": "core.tasks.cleanup_tmp_imports_task",
        "schedule": crontab(hour=3, minute=0),
        "args": (24,),
    },
}
