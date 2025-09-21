# Add these functions to dashboard/utils/cj_extract.py

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union


def extract_dimensions(data: Any) -> dict[str, float | None]:
    """Extract dimensions from product data and return a properly typed dict."""
    if not data:
        return {}
    
    # Initialize with proper type annotation
    dims: dict[str, float | None] = {}
    
    # Handle different data structures
    if isinstance(data, dict):
        for k, v in data.items():
            if v is not None:
                try:
                    dims[k] = float(v)
                except (ValueError, TypeError):
                    dims[k] = None
            else:
                dims[k] = None
        return dims
    
    # If data is not a dict, return empty dict
    return {}


def extract_minimal_from_json_payload(payload: Any) -> List[Dict[str, Any]]:
    """Extract minimal product data from CJ JSON payload."""
    if not payload:
        return []
    
    # Handle different payload structures
    if isinstance(payload, dict):
        # If payload is wrapped in a data/result/items key
        items = payload.get("data", payload.get("result", payload.get("items", payload)))
        if isinstance(items, list):
            return _process_product_list(items)
        elif isinstance(items, dict):
            return [_process_single_product(items)]
    elif isinstance(payload, list):
        return _process_product_list(payload)
    
    return []


def to_csv_rows(data: List[Dict[str, Any]]) -> tuple[List[str], List[List[str]]]:
    """Convert minimal product data to CSV format."""
    if not data:
        return [], []
    
    # Define CSV headers
    headers = [
        "pid", "title", "category", "price", "currency", "sku", 
        "variant_key", "weight", "dimensions", "image", "brand"
    ]
    
    rows = []
    for product in data:
        variants = product.get("variants", [])
        if not variants:
            # Product without variants
            row = [
                str(product.get("pid", "")),
                str(product.get("title", "")),
                str(product.get("category", "")),
                str(product.get("price", "")),
                str(product.get("currency", "USD")),
                str(product.get("sku", "")),
                "",  # variant_key
                str(product.get("weight", "")),
                str(product.get("dimensions", "")),
                str(product.get("image", "")),
                str(product.get("brand", ""))
            ]
            rows.append(row)
        else:
            # Product with variants - one row per variant
            for variant in variants:
                row = [
                    str(product.get("pid", "")),
                    str(product.get("title", "")),
                    str(product.get("category", "")),
                    str(variant.get("price", "")),
                    str(variant.get("currency", "USD")),
                    str(variant.get("sku", "")),
                    str(variant.get("variant_key", "")),
                    str(variant.get("weight", "")),
                    str(variant.get("dimensions", "")),
                    str(variant.get("image", "")),
                    str(product.get("brand", ""))
                ]
                rows.append(row)
    
    return headers, rows


def _process_product_list(products: List[Any]) -> List[Dict[str, Any]]:
    """Process a list of products into minimal format."""
    result = []
    for product in products:
        if isinstance(product, dict):
            processed = _process_single_product(product)
            if processed:
                result.append(processed)
    return result


def _process_single_product(product: Dict[str, Any]) -> Dict[str, Any]:
    """Process a single product into minimal format."""
    # Extract basic product info
    pid = product.get("pid") or product.get("id")
    title = product.get("productNameEn") or product.get("title") or product.get("name")
    category = product.get("categoryName") or product.get("category")
    brand = product.get("brand") or ""
    
    # Extract images
    images = product.get("productImageSet", [])
    if isinstance(images, str):
        try:
            import json
            images = json.loads(images)
        except:
            images = [images] if images else []
    
    main_image = images[0] if images else ""
    
    # Process variants
    variants = []
    raw_variants = product.get("variants", [])
    
    if not raw_variants and product.get("variantSku"):
        # Single variant product
        variant = {
            "sku": product.get("variantSku"),
            "price": product.get("variantSellPrice") or product.get("price"),
            "currency": "USD",
            "variant_key": product.get("variantKey", ""),
            "weight": product.get("variantWeight", ""),
            "dimensions": _extract_dimensions(product),
            "image": product.get("variantImage") or main_image
        }
        variants.append(variant)
    else:
        # Multiple variants
        for var in raw_variants:
            if isinstance(var, dict):
                variant = {
                    "sku": var.get("variantSku", ""),
                    "price": var.get("variantSellPrice") or var.get("price"),
                    "currency": "USD",
                    "variant_key": var.get("variantKey", ""),
                    "weight": var.get("variantWeight", ""),
                    "dimensions": _extract_dimensions(var),
                    "image": var.get("variantImage") or main_image
                }
                variants.append(variant)
    
    return {
        "pid": pid,
        "title": title,
        "category": category,
        "brand": brand,
        "images": images,
        "variants": variants
    }


def _extract_dimensions(data: Dict[str, Any]) -> str:
    """Extract dimensions from variant data as a string."""
    if not data:
        return ""
    
    # Look for various dimension fields
    length = data.get("variantLength") or data.get("length")
    width = data.get("variantWidth") or data.get("width") 
    height = data.get("variantHeight") or data.get("height")
    
    if length or width or height:
        dims = []
        if length:
            dims.append(f"L:{length}")
        if width:
            dims.append(f"W:{width}")
        if height:
            dims.append(f"H:{height}")
        return " x ".join(dims)
    
    return ""


def process_product_data(raw_data: Any) -> Dict[str, Any]:
    """Process raw product data from Commission Junction API."""
    if not raw_data:
        return {}
    
    processed = {}
    
    # Handle product variants safely
    if isinstance(raw_data, dict):
        # Initialize variants as a list if it doesn't exist
        if "variants" not in raw_data:
            raw_data["variants"] = []
        
        # Ensure variants is a list
        if not isinstance(raw_data.get("variants"), list):
            raw_data["variants"] = []
        
        # Process each item
        for item_key, item_data in raw_data.items():
            if isinstance(item_data, dict):
                # Process variants for this item
                variants = item_data.get("variants")
                if variants is not None:
                    # Ensure variants is a list before appending
                    if not isinstance(variants, list):
                        item_data["variants"] = []
                        variants = item_data["variants"]
                    
                    # Type check before appending
                    if isinstance(variants, list):
                        variant_data = {
                            "sku": item_data.get("sku", ""),
                            "price": item_data.get("price", 0),
                            "availability": item_data.get("availability", False),
                        }
                        variants.append(variant_data)
        
        processed = raw_data
    
    return processed


def safe_extract_field(data: Any, field: str, default: Any = None) -> Any:
    """Safely extract a field from data with proper type checking."""
    if isinstance(data, dict):
        return data.get(field, default)
    return default


def validate_product_structure(product: Dict[str, Any]) -> bool:
    """Validate that a product has the required structure."""
    required_fields = ["id", "title", "price"]
    
    for field in required_fields:
        if field not in product:
            return False
    
    return True


def normalize_price(price_value: Any) -> Optional[float]:
    """Normalize price value to float or None."""
    if price_value is None:
        return None
    
    try:
        return float(price_value)
    except (ValueError, TypeError):
        return None


def extract_product_variants(product_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract and normalize product variants."""
    variants = product_data.get("variants", [])
    
    if not isinstance(variants, list):
        return []
    
    normalized_variants = []
    for variant in variants:
        if isinstance(variant, dict):
            normalized_variant = {
                "id": variant.get("id", ""),
                "sku": variant.get("sku", ""),
                "price": normalize_price(variant.get("price")),
                "availability": bool(variant.get("availability", False)),
                "dimensions": extract_dimensions(variant.get("dimensions")),
            }
            normalized_variants.append(normalized_variant)
    
    return normalized_variants