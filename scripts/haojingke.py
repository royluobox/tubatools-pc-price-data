"""Documented third-party HaoJingKe product search; no platform scraping.

Both third-party endpoints label ``price`` as the original listed price.
They are reference listing values, NOT checkout prices. Coupon prices are
retained only as conditional metadata and never silently replace the original.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime

from marketplace import MAX_OFFERS_PER_MODEL, _iso, cny_cents, official_link, title_matches

DOCUMENTED_ENDPOINTS = {
    "jd": "https://api-gw.haojingke.com/index.php/v1/api/jd/goodslist",
    "pdd": "https://api-gw.haojingke.com/index.php/v1/api/pdd/goodslist",
}
PLATFORMS = {"jd": "京东", "pdd": "拼多多"}


def query_haojingke(provider: str, target: dict, api_key: str) -> dict:
    """One capped POST per target, with the secret only in the HTTPS body.

    Provider documentation shows http:// examples; we refuse unencrypted
    transport. Whether its HTTPS endpoint works must be checked with a key.
    """
    if provider not in DOCUMENTED_ENDPOINTS:
        raise ValueError("Unsupported HaoJingKe platform")
    if not api_key or len(api_key) > 512:
        raise ValueError("Missing or malformed API key")
    params = {"apikey": api_key, "keyword": target["query"]}
    if provider == "jd":
        # These are HaoJingKe's names, not the official JD Alliance names.
        params.update({"pageindex": "1", "pagesize": "20", "iscoupon": "0"})
    else:
        params.update({"page": "1", "page_size": "20"})
    request = urllib.request.Request(
        DOCUMENTED_ENDPOINTS[provider],
        data=urllib.parse.urlencode(params).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                 "User-Agent": "TubatoolsPriceFeed/4.0"},
    )
    # Do not send keys to an unexpected redirect host or over plain HTTP.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise ValueError("Provider redirect refused")

    with urllib.request.build_opener(NoRedirect()).open(request, timeout=25) as response:
        if response.geturl() != DOCUMENTED_ENDPOINTS[provider]:
            raise ValueError("Unexpected provider URL")
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("Provider response exceeds 2 MB")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Provider response must be JSON object")
    return payload


def _verified_product_url(platform: str, sku: str, raw: object) -> str | None:
    """Match IDs inside official product links before publishing them."""
    if not sku.isdigit():
        return None
    original = str(raw or "").strip()
    # HaoJingKe's published JD example omits the scheme on item.jd.com.
    # Only this exact official product-link pattern may be upgraded.
    if platform == "京东" and re.fullmatch(r"item\.jd\.com/\d+\.html", original):
        original = "https://" + original
    url = official_link(platform, original)
    if not url:
        return None
    parsed = urllib.parse.urlparse(url)
    if platform == "京东":
        if parsed.hostname not in {"item.jd.com", "item.m.jd.com"}:
            return None
        match = re.fullmatch(r"/(\d+)\.html", parsed.path)
        if not match or match.group(1) != sku:
            return None
        return f"https://item.jd.com/{sku}.html"
    if platform == "拼多多":
        if parsed.hostname not in {"mobile.yangkeduo.com", "yangkeduo.com"}:
            return None
        goods_id = urllib.parse.parse_qs(parsed.query).get("goods_id", [])
        if goods_id != [sku] or parsed.path not in {"/goods.html", "/goods2.html"}:
            return None
        return f"https://mobile.yangkeduo.com/goods.html?goods_id={sku}"
    return None


def parse_haojingke_response(payload: dict, target: dict, observed_at: datetime,
                             provider: str) -> list[dict]:
    """Strict JSON-contract parser, deliberately excluding inferred prices."""
    if provider not in PLATFORMS:
        raise ValueError("Unsupported HaoJingKe platform")
    if str(payload.get("status_code")) != "200":
        raise ValueError("HaoJingKe API returned unsuccessful status")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("HaoJingKe response data must be an object")
    rows = data.get("data" if provider == "jd" else "goods_list")
    if not isinstance(rows, list):
        raise ValueError("HaoJingKe product list missing")

    platform = PLATFORMS[provider]
    offers = []
    for row in rows[:100]:
        if not isinstance(row, dict):
            continue
        sku = str(row.get("goods_id") or "")
        title = row.get("goods_name")
        if not isinstance(title, str) or not title_matches(title, target):
            continue
        url = _verified_product_url(
            platform, sku,
            row.get("materiaurl"),
        )
        cents = cny_cents(row.get("price"))
        if not cents or not url:
            continue
        offer = {
            "source": "HaoJingKe third-party API",
            "platform": platform,
            "skuId": sku,
            "title": title[:200],
            "url": url,
            "price": (cents + 50) // 100,
            "priceCents": cents,
            "priceType": "original-reference",
            "observedAt": _iso(observed_at),
        }
        coupon = cny_cents(row.get("price_after"))
        # This is NOT a confirmed payable price; retain only sensible metadata.
        if coupon and coupon <= cents:
            offer["conditionalCouponPriceCents"] = coupon
        offers.append(offer)

    unique = {(offer["platform"], offer["skuId"]): offer for offer in offers}
    return sorted(unique.values(), key=lambda o: (o["priceCents"], o["skuId"]))[:MAX_OFFERS_PER_MODEL]
