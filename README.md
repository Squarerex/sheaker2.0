remove these line in production:
manage.py
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.dev")

core/wsgi.py
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.prod")  # or dev if you prefer

core/asgi.py
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.prod")