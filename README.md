remove these line in production:
manage.py
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.dev")

core/wsgi.py
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.prod")  # or dev if you prefer

core/asgi.py
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.prod")

run snyc from cli:
python manage.py sync_providers --code=cj --max-pages=2 --page-size=50




####################################
git commit -m "reformatted" --no-verify
