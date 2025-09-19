import os

from .base import *  # noqa

ENV_NAME = "prod"
# --- Debug & hosts ---
DEBUG = False

# Expect ALLOWED_HOSTS from .env, e.g. ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
# (base.py already loads it into ALLOWED_HOSTS via env)
if not ALLOWED_HOSTS:
    # Fail fast if not configured
    ALLOWED_HOSTS = ["sheaker.com", "www.sheaker.com"]
    # You can raise if you prefer:
    # raise RuntimeError("ALLOWED_HOSTS must be set in production")

# Optional: CSRF trusted origins from env (comma-separated)
# CSRF_TRUSTED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
_env_csrf = os.getenv("CSRF_TRUSTED_ORIGINS", "")
if _env_csrf:
    CSRF_TRUSTED_ORIGINS = [u.strip() for u in _env_csrf.split(",") if u.strip()]

# --- Email (configure via env) ---
# Common env vars:
# EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
# EMAIL_HOST=smtp.gmail.com
# EMAIL_PORT=587
# EMAIL_HOST_USER=...
# EMAIL_HOST_PASSWORD=...
# EMAIL_USE_TLS=True
EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True").lower() == "true"
DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "noreply@localhost"
)

# --- Cache (Redis if REDIS_URL provided; else locmem) ---
REDIS_URL = os.getenv("REDIS_URL", "")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "prod-locmem",
        }
    }

# --- Security hardening ---
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True

SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# If behind a reverse proxy / load balancer (e.g., Nginx):
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- Static files ---
# base.py already defines STATIC_ROOT for collectstatic. Ensure you run:
# python manage.py collectstatic

# --- Logging (quiet by default, INFO+) ---
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "formatters": {
        "simple": {
            "format": "[{levelname}] {asctime} {name}: {message}",
            "style": "{",
        }
    },
    "root": {
        "handlers": ["console"],
        "level": os.getenv("DJANGO_LOG_LEVEL", "INFO"),
    },
    "loggers": {
        "django.security": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": True,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": True,
        },
    },
}
