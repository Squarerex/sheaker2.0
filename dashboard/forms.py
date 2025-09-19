from __future__ import annotations

from django import forms

from providers.models import ProviderAccount

DETAIL_CHOICES = [
    ("list_only", "List only (fastest)"),
    ("bulk_detail", "Try bulk detail"),
    ("per_detail", "Per-item detail (slowest)"),
]
MODE_CHOICES = [
    ("download", "Download raw JSON (no DB writes)"),
    ("import", "Import into DB now"),
]


class ProviderSyncForm(forms.Form):
    mode = forms.ChoiceField(choices=MODE_CHOICES, initial="download", widget=forms.RadioSelect)
    detail = forms.ChoiceField(choices=DETAIL_CHOICES, initial="list_only")

    provider = forms.ModelChoiceField(
        queryset=ProviderAccount.objects.filter(is_active=True).order_by("code"),
        required=True,
        help_text="Choose which provider to sync",
    )
    page_size = forms.IntegerField(min_value=1, max_value=200, initial=50, required=False)
    max_pages = forms.IntegerField(min_value=1, max_value=50, initial=1, required=False)
    limit = forms.IntegerField(
        min_value=1,
        max_value=10000,
        required=False,
        help_text="Stop after N items (detail/list). Optional.",
    )
    bulk_size = forms.IntegerField(
        min_value=1,
        max_value=100,
        initial=50,
        required=False,
        help_text="Only used in 'Try bulk detail' mode.",
    )
    keyword = forms.CharField(
        max_length=100, required=False, help_text="CJ /product/list ?keyword="
    )
    category_id = forms.CharField(
        max_length=100, required=False, help_text="CJ /product/list ?categoryId="
    )
    dry_run = forms.BooleanField(
        required=False, initial=False, help_text="Only used in Import mode."
    )

    single_file = forms.BooleanField(
        required=False,
        initial=True,
        help_text="If checked, download one JSON file containing all items; otherwise a ZIP with individual files.",
    )

    def clean(self):
        data = super().clean()
        # keep your defaults
        data.setdefault("page_size", 50)
        data.setdefault("max_pages", 1)
        data.setdefault("bulk_size", 50)

        # new: clamp page/bulk sizes
        data["page_size"] = max(1, min(int(data.get("page_size") or 50), 200))
        data["bulk_size"] = max(1, min(int(data.get("bulk_size") or 50), 100))

        # new: prevent import with list_only (no variants/vid)
        if data.get("mode") == "import" and data.get("detail") == "list_only":
            raise forms.ValidationError(
                "Import requires detail level 'Try bulk detail' or 'Per-item detail'."
            )

        # new: basic credentials sanity
        acct = data.get("provider")
        if acct:
            creds = acct.credentials_json or {}
            missing = [
                k
                for k in (
                    "api_base",
                    "product_list",
                    "product_query",
                    "auth_login",
                    "auth_refresh",
                )
                if not creds.get(k)
            ]
            if missing:
                raise forms.ValidationError(
                    f"Provider credentials missing keys: {', '.join(missing)}. Update them in Admin."
                )
        return data
