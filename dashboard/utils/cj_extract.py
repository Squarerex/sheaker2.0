# dashboard/utils/cj_extract.py
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple


def _parse_dims(standard: str | None) -> Dict[str, float | None]:
    # CJ format: "long=220,width=50,height=270"
    dims = {"long": None, "width": None, "height": None}
    if not standard:
        return dims
    for kv in str(standard).split(","):
        if "=" in kv:
            k, v = kv.split("=", 1)
            k = k.strip()
            v = v.strip()
            try:
                dims[k] = float(v)
            except Exception:
                dims[k] = None
    return dims


def _parse_axes(s: str | None) -> List[str]:
    # Examples: "Color-Size", "Light color-Style", "Style"
    if not s:
        return []
    s = s.replace("–", "-").replace("—", "-")
    return [a.strip() for a in s.split("-") if a.strip()]


def _split_variant_key(
    variant_key: str | None, axes: List[str]
) -> Dict[str, str] | Dict[str, str]:
    """
    Map variantKey onto axes in order.
    If mismatch (counts differ), keep raw string for debugging.
    """
    if not variant_key or not axes:
        return {}
    parts = [p.strip() for p in str(variant_key).split("-")]
    if len(parts) != len(axes):
        return {"_raw": variant_key}
    return {a: val for a, val in zip(axes, parts)}


def _normalize_one_product(p: Dict[str, Any]) -> Dict[str, Any]:
    axes = _parse_axes(p.get("productKeyEn"))
    item = {
        "pid": p.get("pid"),
        "productSku": p.get("productSku"),
        "title": p.get("productNameEn"),
        "category": p.get("categoryName"),
        "axes": axes,
        "images": p.get("productImageSet") or [],
        "variants": [],
    }
    for v in p.get("variants") or []:
        attrs = _split_variant_key(v.get("variantKey"), axes)
        item["variants"].append(
            {
                "vid": v.get("vid"),
                "variantSku": v.get("variantSku"),
                "variantKey": v.get("variantKey"),
                "attributes": attrs,
                "price": v.get("variantSellPrice"),
                "weight_g": v.get("variantWeight"),
                "dims_mm": _parse_dims(v.get("variantStandard")),
                "image": v.get("variantImage"),
            }
        )
    return item


def extract_minimal_from_json_payload(data: Any) -> List[Dict[str, Any]]:
    """
    Accepts:
      - {"items": [...]}   (your current dump format)
      - [...]              (array of products)
      - {...}              (single product)
    Returns a list of normalized products in the minimal schema.
    """
    # normalize to list
    if isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
        products = data["items"]
    elif isinstance(data, list):
        products = data
    elif isinstance(data, dict):
        products = [data]
    else:
        raise ValueError("Unsupported JSON structure: expected dict/list.")

    out = []
    for p in products:
        if not isinstance(p, dict):
            # skip garbage entries
            continue
        out.append(_normalize_one_product(p))
    return out


def to_csv_rows(
    minimal_products: List[Dict[str, Any]],
) -> Tuple[List[str], List[List[str]]]:
    """
    Flatten to one row per variant. Useful for spreadsheets quick-editing.

    Columns:
      pid, title, category, axes(Json), vid, variantSku, variantKey,
      attributes(Json), price, weight_g, long, width, height, image
    """
    headers = [
        "pid",
        "title",
        "category",
        "axes",
        "vid",
        "variantSku",
        "variantKey",
        "attributes",
        "price",
        "weight_g",
        "long",
        "width",
        "height",
        "image",
    ]
    rows: List[List[str]] = []
    for p in minimal_products:
        axes_json = json.dumps(p.get("axes") or [], ensure_ascii=False)
        title = p.get("title") or ""
        category = p.get("category") or ""
        pid = p.get("pid") or ""
        variants = p.get("variants") or []
        if not variants:
            # still output a row so you can see missing variants
            rows.append(
                [
                    pid,
                    title,
                    category,
                    axes_json,
                    "",
                    "",
                    "",
                    "{}",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                ]
            )
            continue
        for v in variants:
            attrs_json = json.dumps(v.get("attributes") or {}, ensure_ascii=False)
            dims = v.get("dims_mm") or {}
            rows.append(
                [
                    pid,
                    title,
                    category,
                    axes_json,
                    v.get("vid") or "",
                    v.get("variantSku") or "",
                    v.get("variantKey") or "",
                    attrs_json,
                    str(v.get("price") or ""),
                    str(v.get("weight_g") or ""),
                    str((dims or {}).get("long") or ""),
                    str((dims or {}).get("width") or ""),
                    str((dims or {}).get("height") or ""),
                    v.get("image") or "",
                ]
            )
    return headers, rows
