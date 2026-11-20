#!/usr/bin/env python3
"""Mirror attributed, manually curated *monthly* DIY reference prices.

Never turn an upstream month into an invented day or a shop/SKU quotation.
The upstream CSVs are CC BY 4.0; no third-party code is executed.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "site" / "data" / "frocloud-monthly.json"
UPSTREAM = "https://github.com/x1shang/frocloud-DIYPCmarket"
RAW_BASE = "https://raw.githubusercontent.com/x1shang/frocloud-DIYPCmarket/main/data/"
FILES = ("cpu-prices.csv", "gpu-prices.csv", "memory-prices.csv")
FIELDS = ("date", "category", "model", "spec", "price_cny", "channel", "note")
MONTH = re.compile(r"^20\d\d-(0[1-9]|1[0-2])$")
SPECIAL = re.compile(r"^20\d\d-(0[1-9]|1[0-2])-下旬$")
MAX_CSV_BYTES = 200_000


def download_csv(filename: str) -> str:
    if filename not in FILES:
        raise ValueError("Unapproved source CSV")
    request = urllib.request.Request(
        RAW_BASE + filename,
        headers={"User-Agent": "TubatoolsCE-Frocloud-Monthly/1.0", "Accept": "text/csv"},
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        if response.geturl() != RAW_BASE + filename:
            raise ValueError("Source redirected; refuse to follow unexpected CSV URL")
        raw = response.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES:
        raise ValueError("Source CSV too large")
    return raw.decode("utf-8-sig")


def model_identity(category: str, model: str, spec: str) -> tuple[str, str, str, str]:
    """Return (stable key, display name, plugin slug, unit); never guess SKUs."""
    if category == "CPU":
        if match := re.fullmatch(r"R([3579])(\d{4,5})([A-Z0-9]*)", model):
            tier, number, suffix = match.groups()
            return f"cpu|RYZEN{tier}{number}{suffix}", f"Ryzen {tier} {number}{suffix}", "cpu", "CNY/item"
        if match := re.fullmatch(r"i([3579])(\d{4,5})([A-Z]*)", model):
            tier, number, suffix = match.groups()
            return f"cpu|I{tier}{number}{suffix}", f"Core i{tier}-{number}{suffix}", "cpu", "CNY/item"
        if match := re.fullmatch(r"U([3579])(\d{3})(K?)( PLUS)?", model):
            tier, number, suffix, plus = match.groups()
            key = f"cpu|ULTRA{tier}{number}{suffix}{'PLUS' if plus else ''}"
            return key, f"Core Ultra {tier} {number}{suffix}{plus or ''}", "cpu", "CNY/item"
        raise ValueError(f"Unrecognized CPU model: {model}")

    if category == "显卡":
        if match := re.fullmatch(r"(\d{4})(Ti|S|TiS|D|DV2)?(8G|10G|12G|16G)?", model):
            number, suffix, memory = match.groups()
            if number.startswith(("4", "5")):
                variant = {None: "", "Ti": " Ti", "S": " Super", "TiS": " Ti Super",
                           "D": " D", "DV2": " D V2"}[suffix]
                capacity = f" {memory[:-1]}GB" if memory else ""
                return (f"vga|RTX{number}{(suffix or '').upper()}{(memory or '').replace('G', 'GB')}",
                        f"RTX {number}{variant}{capacity}", "vga", "CNY/item")
        if match := re.fullmatch(r"(\d{4})(XT|XTX|GRE|GRE10G|GRE12G|XT8G|XT16G)?", model):
            number, suffix = match.groups()
            if number.startswith(("6", "7", "9")):
                suffix = suffix or ""
                return f"vga|RX{number}{suffix.replace('G', 'GB')}", f"RX {number} {suffix}".strip(), "vga", "CNY/item"
        if re.fullmatch(r"B[357]\d{2}", model):
            return f"vga|ARC{model}", f"Arc {model}", "vga", "CNY/item"
        raise ValueError(f"Unrecognized GPU model: {model}")

    if category.startswith("内存 DDR") and model == "内存":
        generation = category.removeprefix("内存 ")
        if not re.fullmatch(r"DDR[345]", generation) or not (re.fullmatch(r"\d+G×\d+", spec) or spec == "AVG"):
            raise ValueError("Unrecognized memory category/spec")
        stable_spec = spec.replace("×", "X")
        return f"memory|FROCLOUD{generation}{stable_spec}", f"{generation} {spec}", "memory", "CNY/GB"
    if category.startswith("固态 PCIE") and model == "固态":
        generation = category.removeprefix("固态 ")
        if not re.fullmatch(r"PCIE[345]\.0", generation) or not re.fullmatch(r"\d+TB", spec):
            raise ValueError("Unrecognized SSD category/spec")
        return f"solid_state_drive|FROCLOUD{generation.replace('.', '')}{spec}", f"SSD {generation} {spec}", "solid_state_drive", "CNY/GB"
    if category == "机械硬盘 HDD" and model == "机械硬盘" and (spec == "AVG" or re.fullmatch(r"\d+TB", spec)):
        return f"hard_drives|FROCLOUDHDD{spec}", f"HDD {spec}（每 GB）", "hard_drives", "CNY/GB"
    raise ValueError(f"Unrecognized category/model/spec: {category}/{model}/{spec}")


def parse_csv(filename: str, content: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")))
    if tuple(reader.fieldnames or ()) != FIELDS:
        raise ValueError(f"Unexpected CSV columns: {filename}")
    rows = []
    seen = set()
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("Malformed source CSV")
        period = row["date"]
        if not (MONTH.fullmatch(period) or SPECIAL.fullmatch(period)):
            raise ValueError(f"Unrecognized period: {period}")
        price_text = row["price_cny"].strip()
        try:
            price = Decimal(price_text)
        except InvalidOperation as error:
            raise ValueError("Non-numeric upstream price") from error
        if not price.is_finite() or not (Decimal("0") < price <= Decimal("500000")):
            raise ValueError("Invalid upstream price")
        key, name, slug, unit = model_identity(row["category"], row["model"], row["spec"])
        if (filename == "memory-prices.csv") != (unit == "CNY/GB"):
            raise ValueError("Category/unit conflicts with source file")
        row_key = (period, key)
        if row_key in seen:
            raise ValueError(f"Duplicate period/model: {row_key}")
        seen.add(row_key)
        rows.append({"month": period, "modelKey": key, "name": name, "slug": slug,
                     "unit": unit, "sourceModel": row["model"], "priceCny": price_text,
                     "note": row["note"]})
    if not rows:
        raise ValueError(f"Empty upstream source: {filename}")
    return rows


def build_feed(sources: dict[str, str], *, min_models: int = 50) -> dict:
    if set(sources) != set(FILES):
        raise ValueError("All three source files are required")
    models: dict[str, dict] = {}
    specials = []
    for filename in FILES:
        for row in parse_csv(filename, sources[filename]):
            if SPECIAL.fullmatch(row["month"]):
                # An in-month snapshot is NOT a daily observation, and cannot
                # be merged into the ordinary monthly average/minimum series.
                specials.append(row)
                continue
            key = row["modelKey"]
            item = models.setdefault(key, {
                "modelKey": key, "name": row["name"], "slug": row["slug"],
                "sourceModel": row["sourceModel"], "unit": row["unit"], "history": [],
            })
            if (item["sourceModel"], item["unit"]) != (row["sourceModel"], row["unit"]):
                raise ValueError("Model identity collision")
            item["history"].append({"month": row["month"], "priceCny": row["priceCny"]})

    if len(models) < min_models:
        raise ValueError("Too few models; refuse truncated dataset")
    for item in models.values():
        item["history"].sort(key=lambda point: point["month"])
        item["latestMonth"] = item["history"][-1]["month"]
        item["latestPriceCny"] = item["history"][-1]["priceCny"]
    ordered = sorted(models.values(), key=lambda item: item["modelKey"])
    through = max(item["latestMonth"] for item in ordered)
    return {
        "schema": 1,
        "source": "FrocloudMonthly",
        "sourceUrl": UPSTREAM,
        "license": "CC BY 4.0",
        "licenseUrl": "https://creativecommons.org/licenses/by/4.0/",
        "timeGrain": "month",
        "dataThrough": through,
        "basis": "作者手工收集的国内全新硬件在售最低参考价，考虑店铺折扣；未记录店铺、SKU、渠道及成交价。",
        "attribution": "数据：x1shang / frocloud-DIYPCmarket（CC BY 4.0，见 sourceUrl）；经格式转换，原月份与数值保留。非实时电商报价。",
        "sourceSha256": {name: hashlib.sha256(sources[name].encode("utf-8")).hexdigest() for name in FILES},
        "models": ordered,
        "specialSnapshots": sorted(specials, key=lambda r: (r["month"], r["modelKey"])),
    }


def validate_feed(feed: dict) -> dict:
    if not isinstance(feed, dict) or feed.get("source") != "FrocloudMonthly" or (
        feed.get("license") != "CC BY 4.0" or feed.get("sourceUrl") != UPSTREAM or
        feed.get("timeGrain") != "month"
    ):
        raise ValueError("Monthly feed source, license, or time grain mismatch")
    models = feed.get("models")
    if not isinstance(models, list) or len(models) < 50:
        raise ValueError("Monthly feed has insufficient models")
    latest_allowed = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m")
    seen_models = set()
    total = 0
    max_month = ""
    for model in models:
        key = model.get("modelKey")
        if not isinstance(key, str) or key in seen_models or "|" not in key:
            raise ValueError("Duplicate or invalid monthly model key")
        seen_models.add(key)
        if model.get("unit") not in {"CNY/item", "CNY/GB"}:
            raise ValueError("Missing/incorrect price unit")
        history = model.get("history")
        if not isinstance(history, list) or not history:
            raise ValueError("Monthly model missing observations")
        months = []
        for point in history:
            month = point.get("month")
            if not isinstance(month, str) or not MONTH.fullmatch(month) or month > latest_allowed:
                raise ValueError("Observation must use a non-future YYYY-MM period")
            try:
                value = Decimal(point["priceCny"])
            except (InvalidOperation, TypeError, KeyError) as error:
                raise ValueError("Observation has no valid CNY price") from error
            if not value.is_finite() or value <= 0 or value > 500_000:
                raise ValueError("Invalid monthly reference price")
            if model["unit"] == "CNY/item" and value != value.to_integral_value():
                raise ValueError("Per-item source prices should be whole CNY")
            months.append(month)
            total += 1
        if months != sorted(set(months)) or model.get("latestMonth") != months[-1] or (
            model.get("latestPriceCny") != history[-1]["priceCny"]
        ):
            raise ValueError("Monthly observations unordered, duplicated, or stale metadata")
        max_month = max(max_month, months[-1])
    if feed.get("dataThrough") != max_month:
        raise ValueError("Inconsistent global coverage")
    for special in feed.get("specialSnapshots", []):
        if not SPECIAL.fullmatch(special.get("month", "")):
            raise ValueError("Special snapshot missing original partial-month period")
        if not special.get("modelKey") or special.get("unit") not in {"CNY/item", "CNY/GB"}:
            raise ValueError("Special snapshot missing identity or unit")
        try:
            special_price = Decimal(special["priceCny"])
        except (InvalidOperation, TypeError, KeyError) as error:
            raise ValueError("Special snapshot missing price") from error
        if not special_price.is_finite() or special_price <= 0 or special_price > 500_000:
            raise ValueError("Special snapshot invalid price")
    return {"status": "valid", "models": len(models), "monthlyPoints": total,
            "specialSnapshots": len(feed.get("specialSnapshots", [])),
            "dataThrough": max_month, "stale": (latest_allowed[:4] != max_month[:4] or
            (int(latest_allowed[:4]) * 12 + int(latest_allowed[5:])) -
            (int(max_month[:4]) * 12 + int(max_month[5:])) > 1)}


def main() -> int:
    try:
        sources = {name: download_csv(name) for name in FILES}
        feed = build_feed(sources)
        validate_feed(feed)
    except (ValueError, UnicodeError, OSError) as error:
        # A bad/missing upstream response must never erase the last valid feed.
        print(f"Frocloud sync skipped ({type(error).__name__}); retained previous snapshot.", file=sys.stderr)
        return 1 if not OUTPUT.exists() else 0

    rendered = json.dumps(feed, ensure_ascii=False, indent=1) + "\n"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if OUTPUT.exists() and OUTPUT.read_text("utf-8") == rendered:
        print(f"Frocloud unchanged: {len(feed['models'])} models through {feed['dataThrough']}")
        return 0
    tmp = OUTPUT.with_suffix(".json.tmp")
    tmp.write_text(rendered, encoding="utf-8")
    tmp.replace(OUTPUT)
    print(f"Frocloud monthly: {len(feed['models'])} models, {len(feed['specialSnapshots'])} partial-month notes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
