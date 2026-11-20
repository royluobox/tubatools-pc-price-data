"""Single-request OneBound JD history diagnostic; never logs credentials or offers.

Run only with repository Actions secrets. A successful probe is not permission to
archive or redistribute the vendor's price history.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

ENDPOINT = "https://api-gw.onebound.cn/jd/item_history_price/"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def summarize(payload: object, requested_sku: str, expected_model: str, *, today: date | None = None) -> dict:
    """Whitelist diagnostic fields; never pass through provider error strings."""
    today = today or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if not isinstance(payload, dict):
        return {"status": "invalid_response", "price_points": 0}

    code = str(payload.get("error_code", ""))
    code = code if re.fullmatch(r"\d{4}", code) else "unknown"
    if code != "0000":
        summary = {"status": "api_error", "error_code": code, "price_points": 0}
        if code == "4003":
            # Never print provider error/reason: some errors echo the API Key.
            reason = " ".join(str(payload.get(field) or "") for field in ("error", "reason"))
            summary["parameter_hint"] = next(
                (field for field in ("num_iid", "cache", "result_type", "secret", "key") if field in reason),
                "unspecified",
            )
        return summary

    items = payload.get("items")
    if not isinstance(items, dict):
        return {"status": "no_history", "error_code": code, "price_points": 0}

    rows = items.get("item")
    if not isinstance(rows, list):
        rows = []

    valid: list[tuple[date, Decimal]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            observed_date = datetime.strptime(str(row["date"])[:10], "%Y-%m-%d").date()
            observed_price = Decimal(str(row["price"]))
        except (KeyError, ValueError, InvalidOperation, TypeError):
            continue
        if not observed_price.is_finite() or not (0 < observed_price < 100_000_000):
            continue
        if observed_date > today:
            continue
        valid.append((observed_date, observed_price))

    observed_sku = str(items.get("num_iid") or "")
    sku_matches = observed_sku == requested_sku
    observed_title = str(items.get("title") or "")
    normalize = lambda value: re.sub(r"[^a-z0-9]", "", value.casefold())
    model_matches = normalize(expected_model) in normalize(observed_title)
    unique_dates = sorted(set(day for day, _ in valid))
    freshness_cutoff = today - timedelta(days=90)
    recent_points = sum(day >= freshness_cutoff for day in unique_dates)

    status = "no_history"
    if valid:
        status = "stale_or_sparse"
    if len(unique_dates) >= 3 and recent_points and sku_matches and model_matches:
        status = "usable_candidate"
    if observed_sku and not sku_matches:
        status = "sku_mismatch"
    if observed_title and not model_matches:
        status = "model_mismatch"

    return {
        "status": status,
        "error_code": code,
        "sku_matches": sku_matches,
        "model_matches": model_matches,
        "price_points": len(rows),
        "valid_points": len(valid),
        "distinct_dates": len(unique_dates),
        "first_date": unique_dates[0].isoformat() if unique_dates else None,
        "last_date": unique_dates[-1].isoformat() if unique_dates else None,
        "recent_90d_dates": recent_points,
        "varying_prices": len({p for _, p in valid}) > 1,
    }


def main() -> int:
    key = os.environ.get("ONEBOUND_API_KEY", "")
    secret = os.environ.get("ONEBOUND_API_SECRET", "")
    sku = os.environ.get("ONEBOUND_SMOKE_SKU", "100147630258")
    model = os.environ.get("ONEBOUND_SMOKE_MODEL", "9800X3D")

    if not key or not secret:
        print(json.dumps({"status": "missing_actions_secrets"}))
        return 2
    if not re.fullmatch(r"\d{8,16}", sku) or not re.fullmatch(r"[\w\d -]{2,32}", model):
        print(json.dumps({"status": "invalid_test_target"}))
        return 2

    # OneBound requires key and secret in GET query parameters. Never print the URL,
    # response body, HTTP exception, request object, or credential-bearing arguments.
    query = urllib.parse.urlencode({
        "key": key,
        "secret": secret,
        "num_iid": sku,
    })
    request = urllib.request.Request(ENDPOINT + "?" + query, headers={"Accept": "application/json"})
    try:
        response = urllib.request.build_opener(NoRedirect).open(request, timeout=25)
        with response:
            if response.status != 200:
                print(json.dumps({"status": "http_failure", "http_code": response.status}))
                return 1
            body = response.read(1_048_577)
        if len(body) > 1_048_576:
            print(json.dumps({"status": "oversized_response"}))
            return 1
        payload = json.loads(body)
    except urllib.error.HTTPError as exc:
        print(json.dumps({"status": "http_failure", "http_code": exc.code}))
        return 1
    except (urllib.error.URLError, OSError, ValueError, UnicodeError, TimeoutError):
        print(json.dumps({"status": "network_or_json_failure"}))
        return 1

    summary = summarize(payload, sku, model)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["status"] == "usable_candidate" else 1


if __name__ == "__main__":
    sys.exit(main())
