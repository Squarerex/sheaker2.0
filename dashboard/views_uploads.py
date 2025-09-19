from __future__ import annotations

import datetime
import io
import json
import json as _json
import uuid as _uuid
from pathlib import Path as _Path
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
from django.utils.encoding import smart_str

from catalog.importers.manual import (
    NORMALIZED_FIELDS,
    commit_import_payload,
    parse_file_to_preview,
)
from dashboard.models import ImportLog

# CJ extractor utils (used in the "tools/cj-extract" endpoint)
from dashboard.utils.cj_extract import extract_minimal_from_json_payload, to_csv_rows

from .authz import role_required
from .forms_uploads import TMP_DIR, BulkUploadForm, CJMinimalExtractForm


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

    # Auto-transform CJ-minimal JSON (variants) -> flat per-variant rows for the uploader
    path_for_preview = _maybe_transform_cj_minimal_to_normalized(path)

    preview = parse_file_to_preview(
        path_for_preview, upsert_flag, mapping=mapping, page=page, per_page=per
    )

    # Provide indices INSIDE preview so template can do preview.start_index
    rows = preview.get("rows", [])
    start_index = (page - 1) * per + 1 if rows else 0
    end_index = start_index + len(rows) - 1 if rows else 0
    preview["start_index"] = start_index
    preview["end_index"] = end_index

    context = {
        "step": "preview",
        "preview": preview,
        "normalized_fields": NORMALIZED_FIELDS,
        # Optional top-level copies (if other template parts use them)
        "page": page,
        "per": per,
    }
    return render(request, "dashboard/products/product_upload.html", context)


# ---- CJ-minimal -> normalized transformation helper --------------------------------
def _kg_from_grams(g) -> str | None:
    try:
        return f"{(float(g) / 1000.0):.3f}"
    except Exception:
        return None


def _cm_from_mm(v) -> float | None:
    try:
        return float(v) / 10.0
    except Exception:
        return None


def _dims_cm_from_mm(dims_mm: dict | None) -> dict:
    dims_mm = dims_mm or {}
    return {
        "l": _cm_from_mm(dims_mm.get("long")),
        "w": _cm_from_mm(dims_mm.get("width")),
        "h": _cm_from_mm(dims_mm.get("height")),
        "unit": "cm",
    }


# --------- color/size extraction from variantKey ---------

_COLOR_WORDS = {
    "black",
    "white",
    "gray",
    "grey",
    "red",
    "blue",
    "navy",
    "indigo",
    "green",
    "moss",
    "bean",
    "pink",
    "smoke",
    "smoky",
    "cream",
    "ivory",
    "coffee",
    "brown",
    "beige",
    "gold",
    "golden",
    "rose",
    "rose gold",
    "silver",
    "cork",
    "walnut",
    "bluish",
    "light",
    "dark",
    "purple",
    "yellow",
    "orange",
}

_AXIS_ALIASES = {
    # If CJ axis names come through, hint how to map them
    "specification": "size",
    "specifications": "size",
    "style": "size",
    "capacity": "size",
    "model": "size",
    "color": "color",
    "colour": "color",
    "light color": "color",
}


def _looks_like_size(tok: str) -> bool:
    t = tok.strip().lower()
    if not t:
        return False
    return (
        "oz" in t
        or "cm" in t
        or "mm" in t
        or "g" in t
        or "kg" in t
        or t.startswith("no ")
        or t.startswith("no.")
        or any(ch.isdigit() for ch in t)
    )


def _looks_like_color(tok: str) -> bool:
    t = tok.strip().lower()
    if not t:
        return False
    return any(w in t for w in _COLOR_WORDS)


def _parse_color_size_from_variant_key(
    variant_key: str, axes: list[str] | None
) -> dict:
    """
    Given CJ 'variantKey' and optional axis names, derive color/size.
    """
    if not variant_key:
        return {}

    axes = [a.strip() for a in (axes or []) if a and isinstance(a, str)]
    ax_hints = [_AXIS_ALIASES.get(a.lower(), a.lower()) for a in axes]

    raw = variant_key.strip()
    # Try most common separators first
    seps = [" - ", "-", "/", "·", "—", "|", ","]
    parts = None
    for sep in seps:
        if sep in raw:
            parts = [p.strip() for p in raw.split(sep) if p.strip()]
            break
    if not parts:
        parts = [raw]

    color = None
    size = None

    if len(parts) == 1:
        p = parts[0]
        if _looks_like_color(p):
            color = p
        elif _looks_like_size(p):
            size = p
    else:
        a, b = parts[0], parts[1]
        # Confident identification
        if _looks_like_size(a) and _looks_like_color(b):
            size, color = a, b
        elif _looks_like_color(a) and _looks_like_size(b):
            color, size = a, b
        else:
            # Fall back to axis hints if provided
            if len(ax_hints) >= 2:
                if "color" in ax_hints[0] and "size" in ax_hints[1]:
                    color, size = a, b
                elif "size" in ax_hints[0] and "color" in ax_hints[1]:
                    size, color = a, b
            # Last resort: heuristic per token
            if color is None and _looks_like_color(a):
                color = a
            if size is None and _looks_like_size(a):
                size = a
            if color is None and _looks_like_color(b):
                color = b
            if size is None and _looks_like_size(b):
                size = b

        # If there are more segments and we still miss color, try joining the tail
        if len(parts) > 2 and color is None:
            tail = " ".join(parts[1:])
            if _looks_like_color(tail):
                color = tail

    out = {}
    if color:
        out["color"] = color
    if size:
        out["size"] = size
    return out


def _maybe_transform_cj_minimal_to_normalized(path: _Path) -> _Path:
    """
    If 'path' points to a CJ-minimal JSON (list of products with 'variants'),
    flatten it into the uploader's expected normalized schema (one row per variant).
    Also:
      - converts weight_g -> weight (kg, string) and dims_mm -> dims (cm JSON),
      - extracts color/size from variantKey into 'attributes',
      - carries vid and variant_key for debugging/fulfillment.
    Otherwise, return the original path unchanged.
    """
    try:
        if path.suffix.lower() != ".json":
            return path
        data = _json.loads(path.read_text(encoding="utf-8"))
        # Accept list[...] or {"items":[...]}
        items = data.get("items") if isinstance(data, dict) else data
        if not isinstance(items, list):
            return path
        # If it doesn't look like our CJ-minimal structure, leave it as-is.
        if not items or not isinstance(items[0], dict) or "variants" not in items[0]:
            return path

        normalized_rows = []

        for p in items:
            title = p.get("title") or p.get("productNameEn") or ""
            category = p.get("category") or p.get("categoryName") or ""
            images = p.get("images") or p.get("productImageSet") or []
            product_main_img = images[0] if images else ""

            axes = p.get("axes") or p.get("productKeyEn") or []
            if isinstance(axes, str):
                # e.g. "Color-Size"
                axes = [
                    a.strip()
                    for a in axes.replace("–", "-").replace("—", "-").split("-")
                    if a.strip()
                ]

            # stable product key fields
            product_key = p.get("pid") or p.get("productSku") or title
            product_productSku = p.get("productSku") or ""

            for v in p.get("variants") or []:
                sku = v.get("variantSku") or ""
                price = v.get("price") or v.get("variantSellPrice")
                vimg = v.get("image") or v.get("variantImage") or product_main_img

                weight = _kg_from_grams(v.get("weight_g") or v.get("variantWeight"))
                dims = _dims_cm_from_mm(v.get("dims_mm") or v.get("variantStandard"))

                # ---- attributes from variantKey + CJ attributes fallback ----
                variant_key = v.get("variantKey") or ""
                attrs_from_key = _parse_color_size_from_variant_key(variant_key, axes)
                cj_attrs = v.get("attributes") or {}
                # normalize CJ attrs if present (e.g., "Color"/"Size"/"Specifications")
                for k, val in list(cj_attrs.items()):
                    lk = k.strip().lower()
                    if "color" in lk and val and "color" not in attrs_from_key:
                        attrs_from_key["color"] = val
                    if (
                        (
                            lk == "size"
                            or lk in _AXIS_ALIASES
                            and _AXIS_ALIASES[lk] == "size"
                        )
                        and val
                        and "size" not in attrs_from_key
                    ):
                        attrs_from_key["size"] = val

                row = {
                    # grouping / identity
                    "product_key": product_key,
                    "product_productSku": product_productSku,
                    # uploader fields
                    "title": title,
                    "description": "",
                    "brand": "",
                    "category_name": category,
                    "subcategory_name": "",
                    "sku": sku,  # Variant.sku
                    "price": str(price) if price is not None else "",
                    "currency": "USD",
                    "weight": weight or "",
                    "dims": (
                        dims if isinstance(dims, dict) and any(dims.values()) else {}
                    ),
                    "media_urls": [vimg] if vimg else images,
                    # NEW: CJ identifiers & attributes for importer
                    "vid": v.get("vid"),
                    "variant_key": variant_key,
                    "attributes": attrs_from_key,
                    # inventory placeholders
                    "qty_available": None,
                    "safety_stock": None,
                    "warehouse": None,
                    "stock_mode": "set",
                }
                normalized_rows.append(row)

        # Write a new temp file next to the original
        new_token = f"{_uuid.uuid4().hex}.json"
        new_path = path.parent / new_token
        new_path.write_text(
            _json.dumps(normalized_rows, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return new_path
    except Exception:
        # If anything goes wrong, fall back to the original file so preview still works
        return path


# ---- Commit & misc endpoints --------------------------------------------------------


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


@role_required(["admin", "editor"])
def cj_minimal_extract(request: HttpRequest) -> HttpResponse:
    """
    Upload a CJ dump (JSON), convert to minimal schema, and return a download.
    """
    if request.method == "GET":
        form = CJMinimalExtractForm()
        return render(request, "dashboard/tools/cj_extract.html", {"form": form})

    form = CJMinimalExtractForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(request, "dashboard/tools/cj_extract.html", {"form": form})

    dump_file = form.cleaned_data["dump_file"]
    output_format = form.cleaned_data["output_format"]

    try:
        # Read and parse JSON payload
        raw = dump_file.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        minimal = extract_minimal_from_json_payload(data)
    except json.JSONDecodeError:
        form.add_error("dump_file", "Invalid JSON file.")
        return render(request, "dashboard/tools/cj_extract.html", {"form": form})
    except Exception as e:
        form.add_error(None, f"Failed to process file: {e}")
        return render(request, "dashboard/tools/cj_extract.html", {"form": form})

    now_stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

    if output_format == "csv":
        headers, rows = to_csv_rows(minimal)
        buf = io.StringIO()
        import csv

        writer = csv.writer(buf)
        writer.writerow(headers)
        writer.writerows(rows)
        filename = f"cj_minimal_variants_{now_stamp}.csv"
        response = HttpResponse(
            buf.getvalue().encode("utf-8-sig"),
            content_type="text/csv; charset=utf-8",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="{smart_str(filename)}"'
        )
        return response

    # default JSON
    content = json.dumps(minimal, ensure_ascii=False, indent=2)
    filename = f"cj_minimal_products_{now_stamp}.json"
    response = HttpResponse(
        content.encode("utf-8"), content_type="application/json; charset=utf-8"
    )
    response["Content-Disposition"] = f'attachment; filename="{smart_str(filename)}"'
    return response
