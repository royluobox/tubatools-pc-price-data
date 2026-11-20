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
    r"二手|拆机|出租|租赁|回收|回购|整机|主机整套|样机|样品展示|代拍|"
    r"散片|板U套装|板U组合|电源线|供电线|连接线|延长线|转换线|"
    r"Laptop|Mobile|笔记本显卡|笔记本GPU|移动版",
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
               captured_at: datetime, *, provider: str = "taobao") -> dict:
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
            if not offer.get("skuId") or not official_link(offer["platform"], offer["url"]) or not offer.get("source"):
                continue
            if not title_matches(offer.get("title", ""), target):
                continue
            if type(offer.get("price")) is not int or offer["price"] <= 0:
                continue
            if type(offer.get("priceCents")) is not int or (
                abs(offer["priceCents"] - offer["price"] * 100) > 50
            ):
                continue
            valid.append(offer)
        # Keep at most twelve distinct listings and, when possible, a balanced
        # sample from both platforms (not twelve variants from one shop).
        valid = list({(item["platform"], item["skuId"]): item for item in
                      sorted(valid, key=lambda x: (x["platform"], x["priceCents"],
                                                   x["skuId"]))}.values())
        if len({row["platform"] for row in valid}) > 1:
            by_platform: dict[str, list[dict]] = {}
            for row in valid:
                by_platform.setdefault(row["platform"], []).append(row)
            chosen = []
            for platform in sorted(by_platform):
                chosen.extend(by_platform[platform][:MAX_OFFERS_PER_MODEL // len(by_platform)])
            valid = chosen[:MAX_OFFERS_PER_MODEL]
        else:
            valid = valid[:MAX_OFFERS_PER_MODEL]
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
    sources = {
        "taobao": (
            "https://developer.alibaba.com/docs/api.htm?apiId=35896",
            "淘宝联盟开放平台物料公开促销标价，不代表实际订单成交价。",
        ),
        "haojingke": (
            "https://www.haojingke.com/open-api/jd",
            "蚂蚁星球（原好京客）第三方 API 的京东/拼多多商品原价参考，"
            "不是实时结算价或已验证券后价。",
        ),
    }
    if provider not in sources:
        raise ValueError("Unsupported marketplace provider")
    source_url, attribution = sources[provider]
    return {
        "schema": 1,
        "source": "RetailAuthorized",
        "sourceUrl": source_url,
        "capturedAt": _iso(captured_at),
        "attribution": attribution + "不包含地区、会员、运费及未明确的补贴。",
        "models": models,
    }
