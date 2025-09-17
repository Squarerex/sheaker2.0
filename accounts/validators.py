from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


class MaximumLengthValidator:
    """
    Enforce an upper bound for plaintext password length before hashing.
    """

    def __init__(self, max_length: int = 64):
        self.max_length = int(max_length)

    def validate(self, password, user=None):
        if password is not None and len(password) > self.max_length:
            raise ValidationError(
                _(
                    "This password is too long. It must contain no more than %(max_length)d characters."
                ),
                code="password_too_long",
                params={"max_length": self.max_length},
            )

    def get_help_text(self):
        return _(
            "Your password must contain no more than %(max_length)d characters."
        ) % {"max_length": self.max_length}
