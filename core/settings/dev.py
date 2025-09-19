from .base import *  # noqa: F401,F403

# ruff: noqa: F405

# --- Env flag (handy for sanity checks) ---
ENV_NAME = "dev"

# --- Debug & hosts ---
DEBUG = True
ALLOWED_HOSTS = ["*"]
CSRF_TRUSTED_ORIGINS = [
    "http://127.0.0.1",
    "http://localhost",
    "http://0.0.0.0",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]

# --- Email (console) ---
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "dev@example.test"

# --- Cache ---
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "dev-locmem",
    }
}

# --- Security relaxed for dev ---
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False

# --- Use SQLite in dev (no psycopg needed) ---
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/accounts/login/"
