from __future__ import annotations

import json
from typing import Dict

from django.contrib import messages
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotAllowed,
    JsonResponse,
)
from django.shortcuts import redirect, render
from django.urls import reverse

from catalog.importers.manual import (
    NORMALIZED_FIELDS,
    commit_import_payload,
    parse_file_to_preview,
)
from dashboard.models import ImportLog

from .authz import role_required
from .forms_uploads import TMP_DIR, BulkUploadForm


def _parse_mapping_from_request(request: HttpRequest) -> Dict[str, str]:
    """
    Accept mapping as mapping[normalized]=supplier_header
    """
    mapping: Dict[str, str] = {}
    for k, v in request.POST.items():
        if k.startswith("mapping[") and k.endswith("]"):
            norm = k[len("mapping[") : -1]
            mapping[norm] = v.strip()
    return mapping


@role_required(["admin", "editor", "marketer"])
def product_upload(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        # Be forgiving about file key: allow 'upload' (our test) or 'file' (some UIs)
        files = request.FILES
        if "upload" not in files and "file" in files:
            files = files.copy()
            files["upload"] = files["file"]

        form = BulkUploadForm(request.POST, files)
        if form.is_valid():
            path, token = form.save_temp()
            update_existing = bool(form.cleaned_data.get("update_existing", True))
            return redirect(
                reverse("dashboard:product_upload_preview")
                + f"?token={token}&upsert={'1' if update_existing else '0'}"
            )
    else:
        form = BulkUploadForm()

    return render(
        request,
        "dashboard/products/product_upload.html",
        {"form": form, "step": "upload"},
    )


@role_required(["admin", "editor", "marketer"])
def product_upload_preview(request: HttpRequest) -> HttpResponse:
    token = request.GET.get("token") or request.POST.get("token")
    upsert_flag = (
        request.GET.get("upsert") or request.POST.get("upsert") or "1"
    ) == "1"
    if not token:
        return HttpResponseBadRequest("Missing token.")

    path = TMP_DIR / token
    if not path.exists():
        messages.error(request, "Upload not found or expired.")
        return redirect("dashboard:product_upload")

    page = int(request.GET.get("page", request.POST.get("page", 1) or 1))
    per = int(request.GET.get("per", request.POST.get("per", 500) or 500))

    # Apply mapping when posted
    mapping = {}
    if request.method == "POST" and request.POST.get("apply_mapping") == "1":
        mapping = _parse_mapping_from_request(request)

    preview = parse_file_to_preview(
        path, upsert_flag, mapping=mapping, page=page, per_page=per
    )

    context = {
        "step": "preview",
        "preview": preview,
        "normalized_fields": NORMALIZED_FIELDS,
    }
    return render(request, "dashboard/products/product_upload.html", context)


@role_required(["admin", "editor", "marketer"])
def product_upload_commit(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    token = request.POST.get("token")
    if not token:
        return HttpResponseBadRequest("Missing token.")

    path = TMP_DIR / token
    if not path.exists():
        messages.error(request, "Upload not found or expired.")
        return redirect("dashboard:product_upload")

    # marketers can only dry-run; admins/editors can commit
    if not _can_commit(request.user) and not request.POST.get("dry_run"):
        return HttpResponseForbidden("You can only perform a dry-run.")

    update_existing = request.POST.get("upsert", "1") == "1"
    dry_run = bool(request.POST.get("dry_run"))

    mapping = _parse_mapping_from_request(request)

    results = commit_import_payload(
        path, update_existing=update_existing, dry_run=dry_run, mapping=mapping
    )

    # Audit trail
    ImportLog.objects.create(
        user=getattr(request, "user", None),
        filename=token,
        upsert=update_existing,
        dry_run=dry_run,
        counts={k: v for k, v in results.items() if k != "errors"},
        errors=results.get("errors", []),
    )

    # Flash summary
    msg = (
        f"{'DRY RUN: ' if dry_run else ''}"
        f"Products {results['products_created']} created / {results['products_updated']} updated; "
        f"Variants {results['variants_created']} created / {results['variants_updated']} updated; "
        f"Media created {results['media_created']}; "
        f"Inventory set {results['inventory_set']} / incremented {results['inventory_incremented']}."
    )
    if results["errors"]:
        messages.warning(
            request, f"{msg} Completed with {len(results['errors'])} warnings."
        )
    else:
        messages.success(request, msg)

    # Keep temp file for later commit only if dry-run
    if not dry_run:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass

    return redirect("dashboard:product_upload")


def _can_commit(user):
    # Only admins/editors can commit
    return (
        user.is_superuser or user.groups.filter(name__in=["admin", "editor"]).exists()
    )


# -------- Sample files for users --------


@role_required(["admin", "editor", "marketer"])
def product_upload_sample_json(request: HttpRequest) -> HttpResponse:
    sample = [
        {
            "title": "Widget A",
            "description": "Example",
            "brand": "ACME",
            "category_name": "Gadgets",
            "subcategory_name": "Widgets",
            "sku": "A-001",
            "price": "19.99",
            "currency": "USD",
            "media_urls": ["https://example.com/image-a.jpg"],
            "qty_available": 20,
            "safety_stock": 2,
            "warehouse": "Main",
            "stock_mode": "set",
        }
    ]
    payload = json.dumps(sample, indent=2)
    return HttpResponse(payload, content_type="application/json")


@role_required(["admin", "editor", "marketer"])
def product_upload_sample_csv(request: HttpRequest) -> HttpResponse:
    csv_text = (
        "title,description,brand,category_name,subcategory_name,sku,price,currency,media_urls,qty_available,safety_stock,warehouse,stock_mode\n"
        'Widget A,Example,ACME,Gadgets,Widgets,A-001,19.99,USD,"[""https://example.com/image-a.jpg""]",20,2,Main,set\n'
    )
    resp = HttpResponse(csv_text, content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="bulk_upload_sample.csv"'
    return resp


@role_required(["admin", "editor", "marketer"])
def product_upload_errors_json(request: HttpRequest) -> HttpResponse:
    token = request.GET.get("token")
    upsert = (request.GET.get("upsert") or "1") == "1"
    if not token:
        return HttpResponseBadRequest("Missing token.")
    p = TMP_DIR / token
    if not p.exists():
        return HttpResponseBadRequest("Upload not found or expired.")

    # Accept mapping on errors view too
    if request.method == "GET":
        # mimic POST-style mapping keys if needed
        mapping = {}
        for k, v in request.GET.items():
            if k.startswith("mapping[") and k.endswith("]"):
                norm = k[len("mapping[") : -1]
                mapping[norm] = v.strip()
    else:
        mapping = _parse_mapping_from_request(request)

    preview = parse_file_to_preview(p, upsert, mapping=mapping)
    errs = [r for r in preview["rows"] if r.get("action") == "error"]
    return JsonResponse({"errors": errs}, json_dumps_params={"indent": 2})
