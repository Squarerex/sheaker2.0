# providers/adapters/cj.py
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Generator, Mapping, Optional

import requests

try:
    from django.core.cache import cache
except Exception:
    cache = None


# -----------------------------
# Public fetch modes (used by UI / services)
# -----------------------------
FETCH_LIST_ONLY = "list_only"
FETCH_BULK_DETAIL = "bulk_detail"
FETCH_PER_DETAIL = "per_detail"  # default/slowest


# -----------------------------
# Errors
# -----------------------------
class RateLimitedError(Exception):
    """Provider returned/indicated a rate-limit (HTTP 429 or vendor-specific code)."""


class CJAuthError(Exception):
    """Authentication/login/refresh failed."""


# -----------------------------
# CJ Adapter
# -----------------------------
class CJAdapter:
    """
    CJ Dropshipping adapter with three fetch modes and a robust mapper.

    credentials (dict) supports:
      - api_base: str (e.g. "https://developers.cjdropshipping.com/api2.0/v1")
      - email: str
      - api_key: str (or password if your tenant uses password login)
      - auth_login: "/authentication/getAccessToken"
      - auth_refresh: "/authentication/refreshAccessToken"
      - product_list: "/product/list"
      - product_query: "/product/query"

      Optional:
      - api_timeout: int (seconds)              (default 30)
      - max_retries: int                        (default 3)
      - min_interval_s: float                   (default 0.3) pacing between calls
      - daily_cap: int                          (default 600) our own soft cap < provider limit
      - platform_token: str (if CJ expects an extra platform key)
      - access_token, refresh_token, access_token_expires, refresh_token_expires
    """

    # safe defaults (we stay well under CJ’s 1000/day)
    DEFAULT_TIMEOUT = 30
    DEFAULT_RETRIES = 3
    DEFAULT_MIN_INTERVAL_S = 0.3
    DEFAULT_DAILY_CAP = 600

    def __init__(
        self,
        *,
        credentials: Mapping[str, Any],
        save_tokens: Optional[Callable[..., None]] = None,
    ):
        self.credentials: Dict[str, Any] = dict(credentials or {})
        self._save_tokens_cb = save_tokens

        # tokens
        self._token: Optional[str] = self.credentials.get("access_token")
        self._refresh_token: Optional[str] = self.credentials.get("refresh_token")
        self._token_expiry: Optional[datetime] = _parse_iso_dt(
            self.credentials.get("access_token_expires")
        )
        self._refresh_expiry: Optional[datetime] = _parse_iso_dt(
            self.credentials.get("refresh_token_expires")
        )

        # HTTP behavior
        self._timeout = int(self.credentials.get("api_timeout") or self.DEFAULT_TIMEOUT)
        self._retries = int(self.credentials.get("max_retries") or self.DEFAULT_RETRIES)
        self._min_interval_s = float(
            self.credentials.get("min_interval_s") or self.DEFAULT_MIN_INTERVAL_S
        )
        self._daily_cap = int(
            self.credentials.get("daily_cap")
            or self.credentials.get("rate_limit_per_day")
            or self.DEFAULT_DAILY_CAP
        )

        # request accounting (in-process; for cross-process use a shared cache/Redis)
        self._last_request_ts: float = 0.0
        self._req_date = _today_str()
        self._req_count = 0

    # ---------- basic config ----------
    def _base(self) -> str:
        return (
            self.credentials.get("api_base") or "https://developers.cjdropshipping.com/api2.0/v1"
        ).rstrip("/")

    def _headers(self) -> Dict[str, str]:
        h = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
            # Many CJ gateways also accept this custom header:
            h["CJ-Access-Token"] = self._token
        if self.credentials.get("platform_token"):
            h["X-Platform-Token"] = self.credentials["platform_token"]
        return h

    # ---------- pacing & counters ----------
    def _cache_key(self) -> str:
        email = (self.credentials.get("email") or "").lower()
        return f"cj:reqcount:{self._req_date}:{email}"

    def _check_reset_counter(self):
        today = _today_str()
        if today != self._req_date:
            self._req_date = today
            self._req_count = 0

    def _budget(self, cost: int = 1):
        self._check_reset_counter()
        if cache:
            key = self._cache_key()
            cache.add(key, 0, timeout=86400)  # create if missing
            new_val = cache.incr(key, cost)
            if new_val > self._daily_cap:
                raise RateLimitedError(f"Internal daily cap reached ({self._daily_cap})")
            self._req_count = new_val
        else:
            if self._req_count + cost > self._daily_cap:
                raise RateLimitedError(f"Internal daily cap reached ({self._daily_cap})")
            self._req_count += cost

    def _maybe_sleep(self):
        if self._min_interval_s <= 0:
            return
        dt = time.time() - self._last_request_ts
        if dt < self._min_interval_s:
            time.sleep(self._min_interval_s - dt)

    # ---------- HTTP helpers ----------
    def _http_get(
        self,
        url: str,
        *,
        headers: Dict[str, str] | None = None,
        params: Dict[str, Any] | None = None,
    ) -> requests.Response:
        headers = headers or {}
        params = params or {}
        last_exc: Optional[Exception] = None

        for attempt in range(1, self._retries + 1):
            self._budget(1)
            self._maybe_sleep()
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=self._timeout)
                self._last_request_ts = time.time()
                if _is_rate_limited(resp):
                    raise RateLimitedError("Provider rate limit reached")
                resp.raise_for_status()
                return resp
            except RateLimitedError:
                # propagate immediately
                raise
            except Exception as e:
                last_exc = e
                # allow retry on transient issues (connection/5xx)
                if attempt >= self._retries:
                    raise _decorate_http_error(e, resp if "resp" in locals() else None)
                # small backoff
                time.sleep(0.5 * attempt)

        # should not reach here
        assert last_exc is not None
        raise last_exc

    def _http_post(
        self,
        url: str,
        *,
        headers: Dict[str, str] | None = None,
        json_body: Dict[str, Any] | None = None,
    ) -> requests.Response:
        headers = headers or {}
        json_body = json_body or {}
        last_exc: Optional[Exception] = None

        for attempt in range(1, self._retries + 1):
            self._budget(1)
            self._maybe_sleep()
            try:
                resp = requests.post(url, headers=headers, json=json_body, timeout=self._timeout)
                self._last_request_ts = time.time()
                if _is_rate_limited(resp):
                    raise RateLimitedError("Provider rate limit reached")
                resp.raise_for_status()
                return resp
            except RateLimitedError:
                raise
            except Exception as e:
                last_exc = e
                if attempt >= self._retries:
                    raise _decorate_http_error(e, resp if "resp" in locals() else None)
                time.sleep(0.5 * attempt)

        assert last_exc is not None
        raise last_exc

    # ---------- auth ----------
    def _ensure_token(self):
        # Use existing token if either we don't know expiry, or it's >10 minutes away
        if self._token and (
            self._token_expiry is None
            or self._token_expiry > datetime.now(timezone.utc) + timedelta(minutes=10)
        ):
            return
        # else, try refresh; if not possible → login
        if self._refresh_token and (
            self._refresh_expiry is None or self._refresh_expiry > datetime.now(timezone.utc)
        ):
            ok = self._refresh()
            if ok:
                return
        self._login()

    def _login(self):
        path = self.credentials.get("auth_login", "/authentication/getAccessToken")
        url = f"{self._base()}{path}"
        email = self.credentials.get("email")
        api_key = self.credentials.get("api_key")
        password = self.credentials.get("password")

        if not email or not (api_key or password):
            raise CJAuthError("Missing CJ credentials: email + (api_key or password) required")

        payload = {"email": email}
        # prefer API key if provided; some tenants require password
        if api_key:
            payload["apiKey"] = api_key
        if password:
            payload["password"] = password

        try:
            resp = self._http_post(
                url,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json_body=payload,
            )
        except RateLimitedError:
            # can't login due to daily limit — no path forward
            raise CJAuthError("Rate-limited during login")

        body = resp.json() or {}
        # normalize common response shapes
        data = body.get("data") or body.get("result") or body
        access = data.get("accessToken") or data.get("token") or data.get("access_token")
        refresh = data.get("refreshToken") or data.get("refresh_token")

        if not access:
            raise CJAuthError(f"Login failed: {body}")

        # expiry (if provided)
        access_exp = _parse_expiry(data.get("expiresIn") or data.get("accessTokenExpiresIn"))
        refresh_exp = _parse_expiry(data.get("refreshTokenExpiresIn"))

        self._assign_tokens(access, refresh, access_exp, refresh_exp)

    def _refresh(self) -> bool:
        if not self._refresh_token:
            return False
        path = self.credentials.get("auth_refresh", "/authentication/refreshAccessToken")
        url = f"{self._base()}{path}"
        try:
            resp = self._http_post(
                url,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json_body={"refreshToken": self._refresh_token},
            )
        except RateLimitedError:
            # Can't refresh today, keep old token if we have it
            return bool(self._token)

        body = resp.json() or {}
        data = body.get("data") or body.get("result") or body
        access = data.get("accessToken") or data.get("token") or data.get("access_token")
        refresh = data.get("refreshToken") or data.get("refresh_token") or self._refresh_token
        if not access:
            return False

        access_exp = _parse_expiry(data.get("expiresIn") or data.get("accessTokenExpiresIn"))
        refresh_exp = _parse_expiry(data.get("refreshTokenExpiresIn")) or self._refresh_expiry
        self._assign_tokens(access, refresh, access_exp, refresh_exp)
        return True

    def _assign_tokens(
        self,
        access: str,
        refresh: Optional[str],
        access_exp: Optional[datetime],
        refresh_exp: Optional[datetime],
    ):
        self._token = access
        self._refresh_token = refresh
        self._token_expiry = access_exp
        self._refresh_expiry = refresh_exp

        if self._save_tokens_cb:
            self._save_tokens_cb(
                self._token,
                self._refresh_token,
                self._token_expiry,
                self._refresh_expiry,
            )

    # ---------- product listing / detail ----------
    def list_products(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        max_pages: int = 1,
        filters: Optional[Dict[str, Any]] = None,
        fetch_mode: str = FETCH_PER_DETAIL,
        bulk_size: int = 50,
    ) -> Generator[Mapping[str, Any], None, None]:
        """
        Yields:
          - if fetch_mode == list_only: summary rows (from /product/list)
          - otherwise: full detail dicts (from /product/query)
        """
        self._ensure_token()

        base = self._base()
        list_path = self.credentials.get("product_list", "/product/list")
        detail_path = self.credentials.get("product_query", "/product/query")
        list_url = f"{base}{list_path}"
        detail_url = f"{base}{detail_path}"

        filters = dict(filters or {})
        page_num = int(page) if page and page > 0 else 1
        pages_done = 0

        while pages_done < max_pages:
            params = {"pageNum": page_num, "pageSize": page_size, **filters}
            resp = self._http_get(list_url, headers=self._headers(), params=params)
            body = resp.json() or {}
            container = body.get("data") or body.get("result") or {}
            items = container.get("list") or []

            if not items:
                break

            if fetch_mode == FETCH_LIST_ONLY:
                for row in items:
                    yield row

            elif fetch_mode == FETCH_BULK_DETAIL:
                pids = [str(x.get("pid") or "").strip() for x in items if x.get("pid")]
                for i in range(0, len(pids), max(1, int(bulk_size))):
                    chunk = [p for p in pids[i : i + int(bulk_size)] if p]
                    if not chunk:
                        continue

                    # Attempt 1: comma-separated pids
                    got_any = False
                    try:
                        d_resp = self._http_get(
                            detail_url,
                            headers=self._headers(),
                            params={"pids": ",".join(chunk)},
                        )
                        d_body = d_resp.json() or {}
                        details = (
                            d_body.get("data") or d_body.get("result") or d_body.get("list") or []
                        )
                        if isinstance(details, dict):
                            details = details.get("list") or []
                        for d in _as_list(details):
                            got_any = True
                            yield d
                    except Exception:
                        pass

                    # Attempt 2: repeated param / array form
                    if not got_any:
                        try:
                            # Some gateways accept repeated key as array (requests will encode pids=[...])
                            d_resp = self._http_get(
                                detail_url,
                                headers=self._headers(),
                                params={"pids": chunk},
                            )
                            d_body = d_resp.json() or {}
                            details = (
                                d_body.get("data")
                                or d_body.get("result")
                                or d_body.get("list")
                                or []
                            )
                            if isinstance(details, dict):
                                details = details.get("list") or []
                            for d in _as_list(details):
                                got_any = True
                                yield d
                        except Exception:
                            pass

                    # Fallback: per-item
                    if not got_any:
                        for pid in chunk:
                            d = self._get_detail_single(detail_url, pid)
                            if d:
                                yield d

            else:  # FETCH_PER_DETAIL
                for row in items:
                    pid = str(row.get("pid") or "").strip()
                    if not pid:
                        continue
                    d = self._get_detail_single(detail_url, pid)
                    if d:
                        yield d

            pages_done += 1
            page_num += 1

    def _get_detail_single(self, detail_url: str, pid: str) -> Mapping[str, Any] | None:
        resp = self._http_get(detail_url, headers=self._headers(), params={"pid": pid})
        b = resp.json() or {}
        d = b.get("data") or b.get("result") or b
        return d

    # ---------- mapping to internal normalized shape ----------
    def map_to_internal(self, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        """
        Turn a raw CJ product detail into our normalized structure:
          {
            product: {...}, variants: [{...}], media: [{url, kind}], external: {external_id}, raw: raw
          }
        """
        # --- IDs & names ---
        external_id = str(raw.get("pid") or "")
        title = raw.get("productNameEn")
        if not title:
            name_set = _as_list(raw.get("productNameSet")) or _json_list(raw.get("productName"))
            title = name_set[0] if name_set else "Untitled"

        description_html = raw.get("description") or ""
        category_id = str(raw.get("categoryId") or "").strip()
        category_path = raw.get("categoryName") or ""
        cat_root, cat_leaf, cat_parts, cat_breadcrumb = _split_category_path(category_path)

        # --- Images ---
        images = _as_list(raw.get("productImageSet"))
        if not images:
            images = _json_list(raw.get("productImage"))
        desc_imgs = _extract_images_from_html(description_html)
        media = [{"url": u, "kind": "image"} for u in images] + [
            {"url": u, "kind": "image"} for u in desc_imgs
        ]

        # --- Variants ---
        variants_out = []
        for v in raw.get("variants") or []:
            sku = str(v.get("variantSku") or "").strip()
            if not sku:
                continue

            price = _to_float(v.get("variantSellPrice"), 0.0)
            attrs = {
                "name": v.get("variantNameEn") or v.get("variantName"),
                "key": v.get("variantKey"),
                "unit": v.get("variantUnit"),
            }
            attrs.update(_parse_color_size_from_key(v.get("variantKey") or ""))

            variants_out.append(
                {
                    "sku": sku,
                    "price": price,
                    "currency": "USD",  # CJ dev API commonly returns USD
                    "attributes": attrs,
                    "weight": _to_float(v.get("variantWeight"), 0.0),
                    "dims": {
                        "length": _to_float(v.get("variantLength"), 0.0),
                        "width": _to_float(v.get("variantWidth"), 0.0),
                        "height": _to_float(v.get("variantHeight"), 0.0),
                    },
                    "is_active": True,
                    "image": v.get("variantImage"),
                }
            )

        product = {
            "title": title,
            "description": description_html,
            "brand": None,  # CJ rarely provides true brand; keep None
            # For Phase 3 we keep categories as strings (service layer avoids FK assignment)
            "category": cat_leaf or cat_root,
            "is_active": True,
            # extras for later phases
            "category_path": cat_breadcrumb,
            "category_root": cat_root,
            "category_leaf": cat_leaf,
            "category_id": category_id,
        }

        return {
            "product": product,
            "variants": variants_out,
            "media": media,
            "external": {"external_id": external_id},
            "raw": raw,
        }


# -----------------------------
# Helpers (pure functions)
# -----------------------------
def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _parse_iso_dt(x) -> Optional[datetime]:
    if not x:
        return None
    try:
        # accept both naive and tz-aware ISO strings
        dt = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _parse_expiry(expires_in) -> Optional[datetime]:
    """Parse expiresIn seconds or None"""
    try:
        sec = int(expires_in)
        return datetime.now(timezone.utc) + timedelta(seconds=sec)
    except Exception:
        return None


def _is_rate_limited(resp: Optional[requests.Response]) -> bool:
    if resp is None:
        return False
    if resp.status_code == 429:
        return True
    try:
        body = resp.json()
        # Some CJ responses include vendor codes like 1600200 for limit reached
        if isinstance(body, dict) and str(body.get("code")) in {"1600200", "1600201"}:
            return True
    except Exception:
        pass
    return False


def _decorate_http_error(e: Exception, resp: Optional[requests.Response]) -> Exception:
    if not resp:
        return e
    try:
        payload = resp.json()
    except Exception:
        payload = resp.text
    return requests.HTTPError(f"{resp.status_code} {resp.reason} :: {payload}", response=resp)


def _to_float(x, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def _json_list(value) -> list[str]:
    """Decode JSON-in-a-string array like '["a","b"]' → list[str]."""
    if not value:
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    if isinstance(value, str):
        v = value.strip()
        if v.startswith("[") and v.endswith("]"):
            try:
                parsed = json.loads(v)
                return [str(x) for x in parsed] if isinstance(parsed, list) else []
            except Exception:
                return []
        return [value]
    return []


def _as_list(value) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _split_category_path(cat_path: Optional[str]):
    """Split breadcrumb 'A > B > C' into (root, leaf, parts, normalized_path)."""
    if not cat_path:
        return None, None, [], ""
    parts = [p.strip() for p in cat_path.split(">")]
    parts = [p for p in parts if p]
    root = parts[0] if parts else None
    leaf = parts[-1] if parts else None
    return root, leaf, parts, " > ".join(parts)


def _extract_images_from_html(html: Optional[str]) -> list[str]:
    if not html:
        return []
    urls: list[str] = []
    for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE):
        urls.append(m.group(1))
    return urls


# ---- Color/Size parsing from variantKey ----
_SIZE_TOKENS = {
    "XXXS",
    "XXS",
    "XS",
    "S",
    "M",
    "L",
    "XL",
    "XXL",
    "XXXL",
    "1XL",
    "2XL",
    "3XL",
    "4XL",
    "5XL",
    "Large Size",
    "Small",
    "Medium",
    "Large",
}
_RE_RING = re.compile(r"^No\.?\s*\d+$", re.I)  # "No 10"
_RE_INCH = re.compile(r"^\d+(\.\d+)?\s*inch(es)?$", re.I)  # "2.5 Inch"
_RE_CM = re.compile(r"^\d+(\.\d+)?\s*cm$", re.I)
_RE_OZ = re.compile(r"^\d+(\.\d+)?\s*oz$", re.I)
_RE_G = re.compile(r"^\d+(\.\d+)?\s*g$", re.I)


def _looks_like_size(token: str) -> bool:
    t = token.strip()
    return (
        t in _SIZE_TOKENS
        or _RE_RING.match(t) is not None
        or _RE_INCH.match(t) is not None
        or _RE_CM.match(t) is not None
        or _RE_OZ.match(t) is not None
        or _RE_G.match(t) is not None
    )


def _parse_color_size_from_key(key: str) -> Dict[str, str]:
    """
    Returns dict with detected attributes, e.g. {'color': 'Black', 'size': 'L'}
    Robust across patterns like:
      Black-L, 32oz-Bean Green, Rose Gold-No 10, 95g Cork, ... 3 Inch
    """
    out: Dict[str, str] = {}
    if not key:
        return out
    parts = [p.strip() for p in key.split("-") if p.strip()]
    if len(parts) == 1:
        # Try "95g Cork" style: size + type
        tokens = parts[0].split()
        if tokens and _looks_like_size(tokens[0]):
            out["size"] = tokens[0]
            if len(tokens) > 1:
                out["color"] = " ".join(tokens[1:])
        else:
            out["option1"] = parts[0]
        return out

    a, b = parts[0], parts[1]
    # Sometimes size suffix attaches at end of second segment: "... 3 Inch"
    b_tokens = b.split()
    if b_tokens and _looks_like_size(b_tokens[-1]):
        out["size"] = b_tokens[-1]
        b = " ".join(b_tokens[:-1]).strip()

    a_is_size = _looks_like_size(a)
    b_is_size = _looks_like_size(b)

    if not a_is_size and b_is_size:
        out["color"] = a
        out["size"] = b
    elif a_is_size and not b_is_size:
        out["size"] = a
        out["color"] = b
    else:
        out["option1"] = a
        out["option2"] = b

    if len(parts) > 2:
        for i, extra in enumerate(parts[2:], start=2):
            out[f"option{i}"] = extra
    return out
