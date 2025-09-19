from __future__ import annotations

import os

from django.contrib import messages
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.db.models import OuterRef, Subquery
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from dashboard.forms import ProviderSyncForm
from providers.models import ProviderAccount, ProviderSyncLog
from providers.services.dump import dump_provider_raw
from providers.services.health import ping_provider
from providers.services.sync import sync_provider_products

from .authz import role_required

signer = TimestampSigner(salt="provider-raw-download")


@role_required(["admin", "editor"])
def provider_sync_now(request, code: str):
    """
    One-click sync for a provider with safe defaults (no filters).
    """
    try:
        account = ProviderAccount.objects.get(code=code)
        if not account.is_active:
            messages.warning(request, f"{code} is inactive.")
            return redirect("dashboard:providers_status")

        result = sync_provider_products(provider_code=code, max_pages=1, page_size=50)
        messages.success(request, f"{code} synced: {result}")
    except Exception as e:
        messages.error(request, f"Sync failed for {code}: {e}")
    return redirect("dashboard:providers_status")


@role_required(["admin", "editor"])
def providers_status(request):
    """
    Health/Status table for providers: latest run per provider + counts/error.
    """
    latest_log_qs = (
        ProviderSyncLog.objects.filter(provider_account=OuterRef("pk"))
        .order_by("-started_at")
        .values("pk")[:1]
    )

    providers = ProviderAccount.objects.all().annotate(
        latest_log_id=Subquery(latest_log_qs)
    )

    latest_logs = {
        log.pk: log
        for log in ProviderSyncLog.objects.filter(
            pk__in=[p.latest_log_id for p in providers if p.latest_log_id]
        )
    }

    rows = []
    for p in providers:
        last = latest_logs.get(p.latest_log_id)
        rows.append(
            {
                "code": p.code,
                "name": p.name,
                "is_active": p.is_active,
                "priority": p.priority,
                "last_status": (last.status if last else "—"),
                "last_started": (last.started_at if last else None),
                "last_finished": (last.finished_at if last else None),
                "duration_ms": (last.duration_ms if last else None),
                "counts": (last.counts if last else {}),
                "first_error": (last.first_error if last else ""),
            }
        )

    return render(request, "dashboard/providers/status.html", {"rows": rows})


@role_required(["admin", "editor"])
def provider_ping(request, code: str):
    """
    Credential check / basic availability ping for a provider.
    """
    try:
        account = ProviderAccount.objects.get(code=code)
        result = ping_provider(account)
        if result.get("ok"):
            messages.success(
                request, f"{code} ping OK (sample_found={result.get('sample_found')})"
            )
        else:
            messages.error(request, f"{code} ping failed: {result.get('error')}")
    except Exception as e:
        messages.error(request, f"{code} ping exception: {e}")
    return redirect("dashboard:providers_status")


@role_required(["admin", "editor"])
def providers_sync_form(request):
    if request.method == "POST":
        form = ProviderSyncForm(request.POST)
        if form.is_valid():
            mode = form.cleaned_data["mode"]
            detail = form.cleaned_data["detail"]
            account = form.cleaned_data["provider"]
            page_size = form.cleaned_data["page_size"]
            max_pages = form.cleaned_data["max_pages"]
            limit = form.cleaned_data.get("limit")
            bulk_size = form.cleaned_data.get("bulk_size") or 50
            keyword = (form.cleaned_data.get("keyword") or "").strip()
            category_id = (form.cleaned_data.get("category_id") or "").strip()
            dry_run = form.cleaned_data.get("dry_run") or False

            filters = {}
            if keyword:
                filters["keyword"] = keyword
            if category_id:
                filters["categoryId"] = category_id

            try:
                if mode == "download":
                    single_file = form.cleaned_data.get("single_file", True)
                    path, count, content_type = dump_provider_raw(
                        account=account,
                        page_size=page_size,
                        max_pages=max_pages,
                        limit=limit,
                        filters=filters or None,
                        fetch_mode=detail,
                        bulk_size=bulk_size,
                        single_file=single_file,
                    )

                    # make a signed token that encodes the on-disk path
                    token = signer.sign(str(path))
                    download_url = request.build_absolute_uri(
                        reverse("dashboard:providers_download", args=[token])
                    )

                    # show a success banner *and* provide the link to click
                    messages.success(
                        request,
                        f"Prepared {count} item(s). "
                        f"<a href='{download_url}' class='button' style='margin-left:8px'>Download file</a>",
                    )

                    # redirect back to the form so the user sees the banner
                    return redirect(reverse("dashboard:providers_sync_form"))

                # mode == "import"
                result = sync_provider_products(
                    provider_code=account.code,
                    page_size=page_size,
                    max_pages=max_pages,
                    limit=limit,
                    filters=filters or None,
                    dry_run=dry_run,
                    fetch_mode="per_detail",  # <- pass through; for safety you can force per_detail here if you want
                )
                mode_label = "DRY-RUN" if dry_run else "APPLIED"
                messages.success(
                    request, f"[{mode_label}] {account.code} sync complete: {result}"
                )
                return redirect(reverse("dashboard:providers_status"))

            except Exception as e:
                messages.error(request, f"{account.code} action failed: {e}")
    else:
        form = ProviderSyncForm()

    return render(request, "dashboard/providers/sync_form.html", {"form": form})


@role_required(["admin", "editor"])
def providers_download(request, token: str):
    """Serve a previously generated file by a signed token, with 1h expiry."""
    try:
        payload = signer.unsign(token, max_age=3600)  # 1 hour
    except (BadSignature, SignatureExpired):
        raise Http404("Download link is invalid or expired.")

    # payload is the absolute path we signed
    path = payload
    if not os.path.exists(path):
        raise Http404("File not found.")
    filename = os.path.basename(path)
    return FileResponse(open(path, "rb"), as_attachment=True, filename=filename)
