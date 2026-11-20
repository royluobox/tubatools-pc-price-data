#!/usr/bin/env python3
"""Opt-in, quota-aware official marketplace collector. Never scrapes shops.

Required GitHub Actions secrets: TBK_APP_KEY, TBK_APP_SECRET, TBK_ADZONE_ID.
Without all three, skip safely and do not alter the published market.json.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from marketplace import build_feed, parse_taobao_response, top_sign

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ROOT / "config" / "market-targets.json"
OUTPUT = ROOT / "site" / "data" / "market.json"
TOP_ENDPOINT = "https://eco.taobao.com/router/rest"


def query_taobao(target: dict, app_key: str, secret: str,
                 adzone: str, now: datetime) -> dict:
    params = {
        "method": "taobao.tbk.dg.material.optional",
        "app_key": app_key,
        "sign_method": "md5",
        "timestamp": now.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S"),
        "format": "json",
        "v": "2.0",
        "adzone_id": adzone,
        "q": target["query"],
        "page_no": "1",
        "page_size": "30",
        "material_id": "2836",
    }
    params["sign"] = top_sign(params, secret)
    data = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(
        TOP_ENDPOINT, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                 "User-Agent": "TubatoolsPriceFeed/3.0"},
    )
    with urllib.request.urlopen(request, timeout=35) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("TOP response exceeds 2 MB")
    return json.loads(raw)


def main() -> int:
    env_names = ("TBK_APP_KEY", "TBK_APP_SECRET", "TBK_ADZONE_ID")
    app_key, secret, adzone = (os.environ.get(name, "").strip() for name in env_names)
    if not all((app_key, secret, adzone)):
        print("TBK not configured: skip retail feed without replacing existing data.")
        return 0
    if not (app_key.isdigit() and adzone.isdigit()):
        raise SystemExit("Invalid TBK public identifiers (AppKey and adzone should be numeric)")

    targets = json.loads(TARGETS.read_text(encoding="utf-8"))
    if not isinstance(targets, list) or not targets:
        raise SystemExit("No reviewed marketplace model targets")
    target_cap = max(1, min(30, int(os.environ.get("TBK_MAX_TARGETS", "12"))))
    pause = max(1.0, min(15.0, float(os.environ.get("TBK_PAUSE_SECONDS", "2"))))

    # The paid/available quota may differ by account. Cap requests at one
    # search per reviewed target and stop rather than blind retry.
    now = datetime.now(timezone.utc)
    observations: dict[str, list[dict]] = {}
    success = 0
    for target in targets[:target_cap]:
        try:
            response = query_taobao(target, app_key, secret, adzone, datetime.now(timezone.utc))
            offers = parse_taobao_response(response, target, now)
            observations[target["modelKey"]] = offers
            success += 1
            print(f"{target['modelKey']}: {len(offers)} verified public product offers")
        except Exception as exc:
            # Never dump request parameters, signatures or credentials.
            print(f"{target['modelKey']}: official API failed: {type(exc).__name__}", file=sys.stderr)
        time.sleep(pause)

    feed = build_feed(observations, targets[:target_cap], now)
    if not success:
        print("No API queries succeeded; retain previous market.json", file=sys.stderr)
        return 1
    if not feed["models"]:
        print("No exact-title matches; retain previous market.json", file=sys.stderr)
        return 1

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(feed, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    temporary.replace(OUTPUT)
    print(f"Market snapshot saved: {len(feed['models'])} models, {success} successful queries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
