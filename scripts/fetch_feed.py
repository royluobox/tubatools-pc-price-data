#!/usr/bin/env python3
"""抓取 VRAMGlass 闲鱼显卡行情，生成插件可读取的公开快照。

只读取公开 API，不保存 API Key。数据来源会在 latest.json 与页面中署名。
历史数据每天最多抓取一次；抓取失败或额度不足时沿用上一份快照，避免把已有历史清空。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://api.vramglass.com/v1"
MARKET = "xianyu"
HISTORY_DAYS = 365
HISTORY_TTL_HOURS = 20
SLEEP_SECONDS = 3.5

# vramglass id, 插件内的型号键, 展示名
MODELS = [
    ("rtx-5090", "vga|RTX5090", "RTX 5090"),
    ("rtx-5080", "vga|RTX5080", "RTX 5080"),
    ("rtx-5070-ti", "vga|RTX5070TI", "RTX 5070 Ti"),
    ("rtx-5070", "vga|RTX5070", "RTX 5070"),
    ("rtx-5060-ti-16gb", "vga|RTX5060TI", "RTX 5060 Ti"),
    ("rtx-5060", "vga|RTX5060", "RTX 5060"),
    ("rx-9070-xt", "vga|RX9070XT", "RX 9070 XT"),
    ("rx-9060-xt-16gb", "vga|RX9060XT", "RX 9060 XT"),
    ("rtx-4060", "vga|RTX4060", "RTX 4060"),
]

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "site" / "data" / "latest.json"


def request_json(path: str) -> dict:
    key = os.environ.get("VRAMGLASS_KEY", "").strip()
    if not key:
        raise SystemExit("缺少环境变量 VRAMGLASS_KEY")
    req = urllib.request.Request(
        API + path,
        headers={
            "Authorization": "Bearer " + key,
            # 与插件客户端保持一致的浏览器 UA，避免部分网关把脚本 UA 当成异常流量。
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.load(resp)


def get_int(obj: dict, *names: str) -> int:
    for name in names:
        value = obj.get(name)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
        if isinstance(value, str):
            try:
                number = int(float(value))
            except ValueError:
                continue
            if number > 0:
                return number
    return 0


def parse_time(text: str) -> datetime | None:
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return value.astimezone(timezone.utc) if value.tzinfo else None
    except (ValueError, AttributeError):
        return None


def load_previous() -> dict:
    try:
        if OUTPUT.exists():
            return json.loads(OUTPUT.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"读取上一份快照失败：{exc}", file=sys.stderr)
    return {}


def fetch_current() -> dict[str, dict]:
    ids = ",".join(model[0] for model in MODELS)
    query = urllib.parse.urlencode({"ids": ids, "market": MARKET, "lang": "zh"})
    payload = request_json(f"/prices?{query}")
    quotes: dict[str, dict] = {}
    for item in payload.get("items") or []:
        model_id = item.get("id")
        if not model_id:
            continue
        for quote in item.get("quotes") or []:
            if str(quote.get("market", "")).lower() != MARKET:
                continue
            status = str(quote.get("status", "")).lower()
            if status and status != "ok":
                continue
            median = get_int(quote, "median")
            if median <= 0:
                continue
            quotes[model_id] = {
                "price": median,
                "low": get_int(quote, "q1", "min", "low", "p25") or median,
                "high": get_int(quote, "q3", "max", "high", "p75") or median,
                "listingCount": get_int(quote, "sample_count", "listing_count", "count"),
                "publishedAt": quote.get("published_at") or "",
            }
            break
    return quotes


def fetch_history(model_id: str) -> list[dict]:
    query = urllib.parse.urlencode({"market": MARKET, "days": HISTORY_DAYS, "lang": "zh"})
    payload = request_json(f"/prices/{urllib.parse.quote(model_id)}/history?{query}")
    points: list[dict] = []
    for point in payload.get("points") or []:
        date = point.get("date")
        median = get_int(point, "median", "price")
        if not date or median <= 0:
            continue
        points.append({"d": date, "median": median})
    points.sort(key=lambda item: item["d"])
    return points


def main() -> int:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    previous = load_previous()
    prev_models = {
        model.get("vramglassId"): model
        for model in previous.get("models") or []
        if isinstance(model, dict) and model.get("vramglassId")
    }
    prev_history_at = parse_time(previous.get("historyCapturedAt", ""))
    history_fresh = (
        prev_history_at is not None
        and now - prev_history_at < timedelta(hours=HISTORY_TTL_HOURS)
    )

    try:
        quotes = fetch_current()
        current_ok = len(quotes) > 0
        print(f"现价：{len(quotes)} 个型号")
    except Exception as exc:  # noqa: BLE001
        print(f"现价抓取失败，沿用上一份快照：{exc}", file=sys.stderr)
        quotes = {}
        current_ok = False

    models = []
    history_all_ok = True
    for model_id, model_key, name in MODELS:
        prev = prev_models.get(model_id, {})
        history: list[dict] = []
        fetched_this_history = history_fresh

        if history_fresh:
            history = prev.get("history") or []
            print(f"{model_id}: 沿用 {len(history)} 天历史")
        else:
            try:
                history = fetch_history(model_id)
                fetched_this_history = bool(history)
                print(f"{model_id}: 历史 {len(history)} 天")
            except urllib.error.HTTPError as exc:
                print(f"{model_id} 历史抓取失败：HTTP {exc.code}", file=sys.stderr)
                history_all_ok = False
            except Exception as exc:  # noqa: BLE001
                print(f"{model_id} 历史抓取失败：{exc}", file=sys.stderr)
                history_all_ok = False
            time.sleep(SLEEP_SECONDS)

        if not history:
            history = prev.get("history") or []
        if not fetched_this_history and not history_fresh:
            history_all_ok = False

        quote = quotes.get(model_id)
        price = (
            quote["price"]
            if quote
            else get_int(prev, "price") or (history[-1]["median"] if history else 0)
        )
        if price <= 0:
            print(f"{model_id} 无数据，跳过")
            continue

        # Per-model freshness: a partial successful API response must not mark
        # previously cached prices of missing GPU models as freshly observed.
        published = parse_time(quote.get("publishedAt", "")) if quote else None
        previous_observed = (
            parse_time(prev.get("observedAt", ""))
            or parse_time(previous.get("capturedAt", ""))
        )
        last_history_date = parse_time(
            (history[-1]["d"] + "T12:00:00Z") if history else ""
        )
        observed_at = (
            (published if published and published <= now else now)
            if quote else (previous_observed or last_history_date or now)
        )

        models.append(
            {
                "vramglassId": model_id,
                "modelKey": model_key,
                "name": name,
                "price": price,
                "low": quote["low"] if quote else get_int(prev, "low") or price,
                "high": quote["high"] if quote else get_int(prev, "high") or price,
                "listingCount": quote["listingCount"] if quote else get_int(prev, "listingCount"),
                "publishedAt": quote["publishedAt"] if quote else prev.get("publishedAt", ""),
                "observedAt": observed_at.isoformat().replace("+00:00", "Z"),
                "historyDays": HISTORY_DAYS,
                "history": history,
            }
        )

    if not models:
        raise SystemExit("没有拿到任何数据，保留上一次快照")

    captured = now if current_ok else (parse_time(previous.get("capturedAt", "")) or now)
    history_fetched_ok = (
        not history_fresh
        and history_all_ok
        and any(model["history"] for model in models)
    )
    history_captured = now if history_fetched_ok else (prev_history_at or now)

    feed = {
        "schema": 1,
        "capturedAt": captured.isoformat().replace("+00:00", "Z"),
        "historyCapturedAt": history_captured.isoformat().replace("+00:00", "Z"),
        "source": "VRAMGlass",
        "sourceUrl": "https://vramglass.com/",
        "market": MARKET,
        "attribution": (
            "数据来源：VRAMGlass（vramglass.com）闲鱼市场在售挂单统计，"
            f"快照时间 {captured.astimezone().strftime('%Y-%m-%d %H:%M')}。"
            "数据仅供个人参考，不构成交易建议；VRAMGlass 与图吧工具箱无隶属关系。"
        ),
        "models": models,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(feed, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(f"已写入 {OUTPUT}（{len(models)} 个型号）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
