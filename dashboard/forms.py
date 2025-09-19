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
    mode = forms.ChoiceField(
        choices=MODE_CHOICES, initial="download", widget=forms.RadioSelect
    )
    detail = forms.ChoiceField(choices=DETAIL_CHOICES, initial="list_only")

    provider = forms.ModelChoiceField(
        queryset=ProviderAccount.objects.filter(is_active=True).order_by("code"),
        required=True,
        help_text="Choose which provider to sync",
    )
    page_size = forms.IntegerField(
        min_value=1, max_value=200, initial=50, required=False
    )
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
        data.setdefault("page_size", 50)
        data.setdefault("max_pages", 1)
        data.setdefault("bulk_size", 50)
        return data
