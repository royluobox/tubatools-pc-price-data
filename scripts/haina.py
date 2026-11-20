"""Authorized Haina product-search adapter. No site crawling or raw-response logs.

Haina's public product/v1 response includes page_price, title, mall_name and
a product URL. Its "product ID" is not guaranteed to be a merchant SKU, so we
derive a stable listing identifier from the returned official product URL.
Any historical price field must be treated as optional; do not synthesize it.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from marketplace import cny_cents, official_link, title_matches, _iso

ENDPOINT = "https://gw-openapi.zhidemai.com/product/v1"
SOURCE = "SMZDM Haina product search API"
PLATFORMS = (
    ("天猫", "天猫"),
    ("京东", "京东"),
    ("淘宝", "淘宝"),
    ("拼多多", "拼多多"),
    ("苏宁", "苏宁"),
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Haina redirected away from official API endpoint")


def query_haina(target: dict, api_key: str) -> dict:
    """One HTTPS call per reviewed target, bounded in response size."""
    if not api_key.strip():
        raise ValueError("Missing Haina API key")
    query = str(target.get("hainaQuery") or target.get("name") or "").strip()
    if not (2 <= len(query) <= 100):
        raise ValueError("Invalid reviewed Haina query")
    body = json.dumps({
        "product_query": query,
        "request_from": "haina",
        "question_id": "tubatools-" + hashlib.sha256(
            target["modelKey"].encode("utf-8")).hexdigest()[:16],
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT, data=body, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": "TubatoolsPriceFeed/5.0", "x-api-key": api_key},
    )
    with urllib.request.build_opener(_NoRedirect()).open(req, timeout=35) as response:
        if response.geturl() != ENDPOINT:
            raise ValueError("Unexpected Haina response URL")
        raw = response.read(8_000_001)
    if len(raw) > 8_000_000:
        raise ValueError("Haina response exceeds 8 MB")
    return json.loads(raw)


def parse_haina_response(payload: dict, target: dict, observed_at: datetime) -> list[dict]:
    """Return only precise, attributable, publicly linked page-list prices."""
    if not isinstance(payload, dict) or payload.get("error_code") != 0:
        raise ValueError("Haina product API returned a non-success status")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        raise ValueError("Haina product data.rows is missing or malformed")
    offers: list[dict] = []
    for row in data["rows"][:150]:
        if not isinstance(row, dict):
            continue
        title = row.get("title")
        if not title_matches(title, target):
            continue
        mall = str(row.get("mall_name") or "")
        platform = next((normalized for hint, normalized in PLATFORMS
                         if hint in mall), None)
        if not platform:
            continue
        url = official_link(platform, str(row.get("url") or ""))
        cents = cny_cents(row.get("page_price"))
        if not url or not cents:
            continue
        # Haina's generic product URL is not documented as a merchant SKU ID.
        # Preserve identity semantics explicitly instead of inventing a SKU.
        listing_id = "url-" + hashlib.sha256(
            (platform + "\n" + url).encode("utf-8")).hexdigest()[:24]
        offers.append({
            "source": SOURCE,
            "platform": platform,
            "skuId": listing_id,
            "idType": "source-listing-url",
            "title": title[:200],
            "url": url,
            "price": (cents + 50) // 100,
            "priceCents": cents,
            "priceType": "retail-page-listed",
            "observedAt": _iso(observed_at),
        })
    unique = {(offer["platform"], offer["skuId"]): offer for offer in offers}
    return sorted(unique.values(), key=lambda x: (x["priceCents"], x["skuId"]))[:48]


def record_daily_history(feed: dict, captured_at: datetime, previous: dict | None = None) -> dict:
    """Accumulate only dates actually sampled; do not backfill missing days.

    The published chart uses one measured daily median (the last collection
    that day, in China time). We never import fabricated or other-provider
    history. This begins on the first authorized collection date.
    """
    if captured_at.tzinfo is None:
        raise ValueError("Captured time must be timezone aware")
    if feed.get("sourceUrl") != "https://ai.zhidemai.com/haina-platform/product_search_pro":
        raise ValueError("Not a Haina market feed")
    past = {}
    if isinstance(previous, dict) and previous.get("sourceUrl") == feed["sourceUrl"]:
        past = {row.get("modelKey"): row for row in previous.get("models", [])
                if isinstance(row, dict)}
    today = captured_at.astimezone(ZoneInfo("Asia/Shanghai")).date()
    earliest = today - timedelta(days=364)
    for model in feed.get("models", []):
        samples: dict[str, int] = {}
        for point in past.get(model["modelKey"], {}).get("history", []) or []:
            if not isinstance(point, dict):
                continue
            day = point.get("d")
            median = point.get("median")
            if not isinstance(day, str) or type(median) is not int:
                continue
            try:
                parsed = datetime.strptime(day, "%Y-%m-%d").date()
            except ValueError:
                continue
            if earliest <= parsed < today and 0 < median < 500000:
                samples[day] = median
        samples[today.isoformat()] = model["price"]
        model["history"] = [{"d": day, "median": samples[day]}
                            for day in sorted(samples)]
        model["historyDays"] = len(samples)
    return feed
