#!/usr/bin/env python3
"""Publication gate: validates real JSON feeds without contacting any API."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from marketplace import official_link, title_matches

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data"
TARGETS = {
    row["modelKey"]: row
    for row in json.loads((ROOT / "config" / "market-targets.json").read_text("utf-8"))
}


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def validate(path: Path, *, optional: bool = False) -> dict:
    if optional and not path.exists():
        return {"status": "not-configured", "models": 0}
    payload = json.loads(path.read_text(encoding="utf-8"))
    captured = parse_utc(payload["capturedAt"])
    if captured > datetime.now(timezone.utc) + timedelta(minutes=10):
        raise ValueError("Snapshot capturedAt lies in the future")
    models = payload.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("Feed is empty or has no models array")
    names = set()
    offers = 0
    flags = Counter()
    for model in models:
        key = model.get("modelKey") or model.get("vramglassId")
        if not key or key in names:
            raise ValueError(f"Missing or duplicate model key: {key}")
        names.add(key)
        price = model.get("price")
        if type(price) is not int or not (0 < price < 500_000):
            raise ValueError(f"Invalid model price: {key}")
        if not (model.get("name") or model.get("Name")):
            raise ValueError(f"Missing model name: {key}")
        history = model.get("history") or []
        if len(history) >= 20 and len({p.get("median") for p in history}) == 1:
            flags["flat_reference_histories"] += 1

        if path.name != "market.json":
            continue
        if payload.get("source") != "RetailAuthorized":
            raise ValueError("Market feed must have a RetailAuthorized source")
        target = TARGETS.get(key)
        if not target:
            raise ValueError(f"Unreviewed model in market feed: {key}")
        quotes = model.get("offers") or []
        if not quotes or len(quotes) > 12:
            raise ValueError(f"Missing or excessive retail quotes for {key}")
        sku_keys = set()
        for quote in quotes:
            platform = quote.get("platform", "")
            url = quote.get("url", "")
            sku = quote.get("skuId", "")
            observed = parse_utc(quote["observedAt"])
            if not (quote.get("source") and sku and official_link(platform, url)):
                raise ValueError(f"Invalid marketplace provenance: {key}")
            if not title_matches(quote.get("title", ""), target):
                raise ValueError(f"Marketplace model mismatch: {key}/{sku}")
            if observed > captured + timedelta(minutes=5):
                raise ValueError(f"Quote date after capture: {key}/{sku}")
            if type(quote.get("price")) is not int or quote["price"] <= 0:
                raise ValueError(f"Invalid quote price: {key}/{sku}")
            if type(quote.get("priceCents")) is not int or (
                abs(quote["priceCents"] - quote["price"] * 100) > 50
            ):
                raise ValueError(f"Invalid cents precision: {key}/{sku}")
            if (platform, sku) in sku_keys:
                raise ValueError(f"Duplicate retail SKU: {key}/{sku}")
            sku_keys.add((platform, sku))
            offers += 1
    age_hours = round((datetime.now(timezone.utc) - captured).total_seconds() / 3600, 1)
    return {"status": "valid", "models": len(models), "offers": offers,
            "ageHours": age_hours, **flags}


def main() -> int:
    try:
        result = {
            "VRAMGlass": validate(DATA / "latest.json"),
            "ZOL": validate(DATA / "catalog.json"),
            "Marketplace": validate(DATA / "market.json", optional=True),
        }
    except (KeyError, ValueError, TypeError, OSError, json.JSONDecodeError) as exc:
        print(f"FEED VALIDATION FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
