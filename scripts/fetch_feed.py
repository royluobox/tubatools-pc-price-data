#!/usr/bin/env python3
"""抓取 VRAMGlass 闲鱼显卡行情，生成插件可读取的公开快照。

只读取公开 API，不保存 API Key。数据来源会在 latest.json 与页面中署名。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.vramglass.com/v1"
MARKET = "xianyu"
HISTORY_DAYS = 365
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
    ("rx-9070", "vga|RX9070", "RX 9070"),
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


def fetch_current() -> tuple[dict, dict]:
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
    return quotes, payload


def fetch_history(model_id: str) -> list[dict]:
    query = urllib.parse.urlencode({"market": MARKET, "days": HISTORY_DAYS, "lang": "zh"})
    payload = request_json(
        f"/prices/{urllib.parse.quote(model_id)}/history?{query}"
    )
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
    captured = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        quotes, _ = fetch_current()
        print(f"现价：{len(quotes)} 个型号")
    except Exception as exc:  # noqa: BLE001
        print(f"现价抓取失败，继续尝试历史：{exc}", file=sys.stderr)
        quotes = {}

    models = []
    for model_id, model_key, name in MODELS:
        history: list[dict] = []
        try:
            history = fetch_history(model_id)
        except urllib.error.HTTPError as exc:
            print(f"{model_id} 历史抓取失败：HTTP {exc.code}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"{model_id} 历史抓取失败：{exc}", file=sys.stderr)
        time.sleep(SLEEP_SECONDS)

        quote = quotes.get(model_id)
        if not quote and not history:
            print(f"{model_id} 无数据，跳过")
            continue

        price = quote["price"] if quote else history[-1]["median"]
        models.append(
            {
                "vramglassId": model_id,
                "modelKey": model_key,
                "name": name,
                "price": price,
                "low": quote["low"] if quote else price,
                "high": quote["high"] if quote else price,
                "listingCount": quote["listingCount"] if quote else 0,
                "publishedAt": quote["publishedAt"] if quote else "",
                "historyDays": HISTORY_DAYS,
                "history": history,
            }
        )
        print(f"{model_id}: ¥{price:,}，历史 {len(history)} 天")

    if not models:
        raise SystemExit("没有拿到任何数据，保留上一次快照")

    feed = {
        "schema": 1,
        "capturedAt": captured.isoformat().replace("+00:00", "Z"),
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
