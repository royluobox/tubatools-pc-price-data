"""Strict, source-attributed marketplace observations for the CE price plugin.

Only authorized official API results may enter this feed. ZOL reference prices,
used listings and scraped search snippets are intentionally not retail offers.
All monetary values in the public feed are integer CNY, rounded from Decimal.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlparse, urlunparse

MAX_OFFERS_PER_MODEL = 12
MAX_SOURCE_AGE = timedelta(hours=48)
BAD_TITLES = re.compile(
    r"支架|转接|扩展坞|转接线|显卡坞|水冷头|风扇替换|维修|空盒|贴纸|"
    r"二手|拆机|出租|租赁|回收|回购|整机|主机整套|样机|样品展示|代拍",
    re.IGNORECASE,
)
ALLOWED_HOSTS = {
    "淘宝": ("taobao.com",),
    "天猫": ("tmall.com", "tmall.hk"),
    "京东": ("jd.com", "3.cn"),
    "拼多多": ("pinduoduo.com", "yangkeduo.com"),
    "苏宁": ("suning.com",),
}


def top_sign(params: dict[str, str], secret: str) -> str:
    """Taobao TOP sign_method=md5: MD5(secret + sorted key/value + secret).

    The sign parameter is excluded. No secret is logged or published.
    """
    values = "".join(
        str(key) + str(value)
        for key, value in sorted(params.items())
        if key != "sign" and value is not None
    )
    return hashlib.md5((secret + values + secret).encode("utf-8")).hexdigest().upper()


def official_link(platform: str, raw: str) -> str | None:
    """Only user-facing official HTTPS product links are accepted."""
    try:
        url = urlparse(raw.strip())
        host = (url.hostname or "").rstrip(".").lower()
        if url.scheme not in {"http", "https"} or not host:
            return None
        if url.username or url.password or url.port not in (None, 443, 80):
            return None
        if not any(host == allowed or host.endswith("." + allowed)
                   for allowed in ALLOWED_HOSTS.get(platform, ())):
            return None
        # Original TBK responses may still contain http:// links. Upgrade only
        # verified official domains; never follow redirects or query arbitrary URLs.
        return urlunparse(("https", host, url.path, "", url.query, ""))
    except (ValueError, AttributeError):
        return None


def cny_cents(value: object) -> int | None:
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or not (Decimal("1") <= amount < Decimal("500000")):
            return None
        return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError, ValueError):
        return None


def title_matches(title: str, target: dict) -> bool:
    if not isinstance(title, str) or BAD_TITLES.search(title):
        return False
    required = target.get("required", [])
    return bool(required) and all(re.search(pattern, title, re.IGNORECASE)
                                  for pattern in required) and not any(
        re.search(pattern, title, re.IGNORECASE)
        for pattern in target.get("excluded", []))


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_taobao_response(payload: dict, target: dict, observed_at: datetime) -> list[dict]:
    """Normalize only exact-title matches from the documented TBK API JSON."""
    if "error_response" in payload:
        error = payload["error_response"]
        raise ValueError(f"TOP API error code={error.get('code')} sub_code={error.get('sub_code')}")
    root = payload.get("tbk_dg_material_optional_response")
    if not isinstance(root, dict):
        raise ValueError("TOP response is missing tbk_dg_material_optional_response")
    rows = root.get("result_list", {}).get("map_data", [])
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        raise ValueError("TOP result_list.map_data must be a list")

    offers = []
    for row in rows[:200]:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "")
        if not title_matches(title, target):
            continue
        platform = "天猫" if str(row.get("user_type")) == "1" else "淘宝"
        url = official_link(platform, str(row.get("item_url") or ""))
        sku = str(row.get("num_iid") or row.get("item_id") or "")
        cents = cny_cents(row.get("zk_final_price"))
        if not url or not sku.isdigit() or not cents:
            continue
        price = (cents + 50) // 100
        offers.append({
            "source": "Taobao Alliance TOP API",
            "platform": platform,
            "skuId": sku,
            "title": title[:200],
            "url": url,
            "price": price,
            "priceCents": cents,
            "priceType": "promotional-listed",
            "observedAt": _iso(observed_at),
        })
    # Distinct SKU, deterministic order and bounded payload.
    unique = {(offer["platform"], offer["skuId"]): offer for offer in offers}
    return sorted(unique.values(), key=lambda item: (item["price"], item["skuId"]))[:MAX_OFFERS_PER_MODEL]


def build_feed(observations: dict[str, list[dict]], targets: list[dict],
               captured_at: datetime) -> dict:
    """Never fabricate missing prices/history or roll stale offers forward."""
    if captured_at.tzinfo is None:
        raise ValueError("captured_at must include timezone")
    models = []
    for target in targets:
        offers = observations.get(target["modelKey"], [])
        valid = []
        for offer in offers:
            try:
                observed = datetime.fromisoformat(offer["observedAt"].replace("Z", "+00:00"))
            except (ValueError, KeyError):
                continue
            if observed > captured_at + timedelta(minutes=5) or captured_at - observed > MAX_SOURCE_AGE:
                continue
            if not official_link(offer["platform"], offer["url"]) or not offer.get("source"):
                continue
            if not isinstance(offer.get("price"), int) or offer["price"] <= 0:
                continue
            valid.append(offer)
        if not valid:
            continue
        prices = sorted(offer["price"] for offer in valid)
        middle = len(prices) // 2
        median = prices[middle] if len(prices) % 2 else (prices[middle - 1] + prices[middle] + 1) // 2
        models.append({
            "modelKey": target["modelKey"],
            "name": target["name"],
            "slug": target["slug"],
            "price": median,
            "low": prices[0],
            "high": prices[-1],
            "skuCount": len(valid),
            "offers": valid,
            # Historical prices must be observed over time, not generated by
            # expanding today's point into preceding calendar dates.
            "history": [],
        })
    return {
        "schema": 1,
        "source": "RetailAuthorized",
        "sourceUrl": "https://developer.alibaba.com/docs/api.htm?apiId=35896",
        "capturedAt": _iso(captured_at),
        "attribution": (
            "淘宝联盟开放平台授权物料搜索；展示价并非订单成交价，"
            "不包含地区、会员、运费及未明确的券后补贴。"
        ),
        "models": models,
    }
