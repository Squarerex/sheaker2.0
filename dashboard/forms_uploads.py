from __future__ import annotations

import uuid
from pathlib import Path
from typing import IO, Optional, Tuple

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError

# Temp dir (ensure it exists; add to .gitignore)
TMP_DIR: Path = getattr(settings, "TMP_IMPORT_DIR", Path(settings.BASE_DIR) / "tmp_imports")
ALLOWED_EXTS = {".json", ".csv"}


class BulkUploadForm(forms.Form):
    """
    Accepts either 'upload' (template manual input) or 'file' (tests/other UIs).
    We validate whichever is provided and persist it to TMP_DIR.
    """

    # Both are optional individually, but one is required in clean()
    upload = forms.FileField(label="CSV or JSON", required=False)
    file = forms.FileField(label="CSV or JSON (alt)", required=False)

    update_existing = forms.BooleanField(
        required=False,
        initial=True,
        label="Upsert existing products/variants (uncheck for Create-only)",
    )

    # internal holder for the picked/validated file
    _picked_file: Optional[IO[bytes]] = None

    def _validate_uploaded_file(self, f: IO[bytes]) -> IO[bytes]:
        name = getattr(f, "name", "")
        ext = Path(name).suffix.lower()
        if ext not in ALLOWED_EXTS:
            raise ValidationError("Only .json or .csv files are allowed.")
        size = getattr(f, "size", None)
        if size and size > 1_000_000_000:  # ~1GB guardrail
            raise ValidationError("File too large (limit ~1GB).")
        return f

    def clean(self):
        data = super().clean()
        f = data.get("upload") or data.get("file")
        if not f:
            raise ValidationError("Please choose a JSON or CSV file.")
        self._picked_file = self._validate_uploaded_file(f)
        return data

    def save_temp(self) -> Tuple[Path, str]:
        """
        Persist the uploaded file to tmp_imports and return (path, token).
        """
        if not self._picked_file:
            # Fallback in case save_temp is called without clean()
            f = self.cleaned_data.get("upload") or self.cleaned_data.get("file")
            if not f:
                raise ValidationError("No file to save.")
            self._picked_file = self._validate_uploaded_file(f)

        TMP_DIR.mkdir(parents=True, exist_ok=True)

        f = self._picked_file
        name = getattr(f, "name", "upload")
        ext = Path(name).suffix.lower() or ".json"
        token = f"{uuid.uuid4().hex}{ext}"
        dest = TMP_DIR / token

        with dest.open("wb") as out:
            # Django UploadedFile supports .chunks(); SimpleUploadedFile also does.
            for chunk in f.chunks():  # type: ignore[attr-defined]
                out.write(chunk)

        return dest, token


class CJMinimalExtractForm(forms.Form):
    dump_file = forms.FileField(
        label="CJ JSON dump",
        help_text="Upload a CJ dump: {'items': [...]}, a single product, or an array of products.",
    )
    output_format = forms.ChoiceField(
        choices=[("json", "JSON (minimal)"), ("csv", "CSV (variants rows)")],
        initial="json",
        label="Output format",
    )
