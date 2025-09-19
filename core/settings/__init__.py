import os

env = os.getenv("DJANGO_ENV", "dev").lower()  # dev by default
if env == "prod":
    from .prod import *  # noqa
else:
    from .dev import *  # noqa
