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
pre-commit clean
pre-commit autoupdate
pre-commit install
pre-commit run -a

git add -A
git commit -m "chore(settings): make dotenv optional for mypy; remove stray import; tidy prod"
git push
