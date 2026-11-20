#!/usr/bin/env python3
"""Opt-in, quota-aware marketplace collectors; never scrape shopping sites.

HJK_API_KEY enables the documented third-party JD/PDD product endpoints.
TBK credentials remain available as a separate official API fallback.
No live requests without explicit publication approval or smoke-test mode.
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

from haojingke import parse_haojingke_response, query_haojingke
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
    smoke = os.environ.get("MARKET_SMOKE_TEST", "").lower() == "true"
    approved = os.environ.get("MARKET_PUBLISH_ENABLED", "").lower() == "true"
    if not approved and not smoke:
        print("Market publication not approved: skip all third-party queries and writes.")
        return 0

    hjk_key = os.environ.get("HJK_API_KEY", "").strip()
    app_key, secret, adzone = (
        os.environ.get(name, "").strip()
        for name in ("TBK_APP_KEY", "TBK_APP_SECRET", "TBK_ADZONE_ID")
    )
    requested = os.environ.get("MARKET_PROVIDER", "auto").strip().lower()
    if requested not in {"auto", "haojingke", "taobao"}:
        raise SystemExit("MARKET_PROVIDER must be auto, haojingke or taobao")
    provider = ("haojingke" if hjk_key else "taobao") if requested == "auto" else requested
    if provider == "haojingke" and not hjk_key:
        print("HJK not configured: skip without replacing existing data.")
        return 1 if smoke else 0
    if provider == "taobao" and not all((app_key, secret, adzone)):
        print("TBK not configured: skip without replacing existing data.")
        return 1 if smoke else 0
    if provider == "taobao" and not (app_key.isdigit() and adzone.isdigit()):
        raise SystemExit("Invalid TBK public identifiers (AppKey and adzone should be numeric)")

    targets = json.loads(TARGETS.read_text(encoding="utf-8"))
    if not isinstance(targets, list) or not targets:
        raise SystemExit("No reviewed marketplace model targets")
    smoke_model = os.environ.get("MARKET_SMOKE_MODEL_KEY", "").strip() if smoke else ""
    if smoke_model:
        targets = [item for item in targets if item["modelKey"] == smoke_model]
        if len(targets) != 1:
            raise SystemExit("MARKET_SMOKE_MODEL_KEY must select one reviewed model")
    target_cap = max(1, min(30, int(os.environ.get(
        "HJK_MAX_TARGETS" if provider == "haojingke" else "TBK_MAX_TARGETS",
        "4" if provider == "haojingke" else "12",
    ))))
    if smoke:
        target_cap = min(target_cap, 2)
    pause = max(1.0, min(15.0, float(os.environ.get("MARKET_PAUSE_SECONDS", "2"))))
    platforms = [x.strip() for x in os.environ.get("HJK_PLATFORMS", "jd,pdd").split(",")]
    if provider == "haojingke" and (not platforms or len(platforms) != len(set(platforms)) or
                                   any(x not in {"jd", "pdd"} for x in platforms)):
        raise SystemExit("HJK_PLATFORMS must list unique jd/pdd identifiers")

    # The paid/available quota may differ by account. Cap requests at one
    # search per reviewed target and stop rather than blind retry.
    now = datetime.now(timezone.utc)
    observations: dict[str, list[dict]] = {}
    success = 0
    matched = 0
    for target in targets[:target_cap]:
        sub_sources = platforms if provider == "haojingke" else ["taobao"]
        for source in sub_sources:
            response = None
            try:
                if source == "taobao":
                    response = query_taobao(target, app_key, secret, adzone,
                                            datetime.now(timezone.utc))
                    offers = parse_taobao_response(response, target, now)
                else:
                    response = query_haojingke(source, target, hjk_key)
                    offers = parse_haojingke_response(response, target, now, source)
                observations.setdefault(target["modelKey"], []).extend(offers)
                success += 1
                matched += len(offers)
                rows_count = "unknown"
                if source in {"jd", "pdd"} and isinstance(response.get("data"), dict):
                    rows = response["data"].get("data" if source == "jd" else "goods_list")
                    if isinstance(rows, list):
                        rows_count = str(len(rows))
                print(f"{target['modelKey']}/{source}: {rows_count} returned rows, "
                      f"{len(offers)} strictly matched offers")
            except Exception as exc:
                # Never log request URL, query text, credentials or response bodies.
                detail = type(exc).__name__
                if source in {"jd", "pdd"} and isinstance(response, dict):
                    status = response.get("status_code")
                    status_label = (str(status) if str(status).isdigit() and
                                    len(str(status)) <= 5 else "missing-or-nonnumeric")
                    data = response.get("data")
                    detail += f" (status={status_label}, data_type={type(data).__name__})"
                    if isinstance(data, dict):
                        # Only fixed schema names: never echo arbitrary API content.
                        known = ("goods_list", "list", "data", "goods_search_response")
                        detail += ", known_fields=" + ",".join(k for k in known if k in data)
                print(f"{target['modelKey']}/{source}: request failed: {detail}",
                      file=sys.stderr)
            time.sleep(pause)

    if smoke:
        print(f"Smoke test only: {success} accepted responses, {matched} exact SKU matches;"
              " no snapshot written.")
        return 0 if success and matched else 1

    feed = build_feed(observations, targets[:target_cap], now, provider=provider)
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
