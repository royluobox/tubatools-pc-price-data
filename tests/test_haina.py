"""Offline contract coverage for Haina marketplace search and real observed history."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from haina import parse_haina_response, record_daily_history
from marketplace import build_feed

TARGETS = json.loads((ROOT / "config" / "market-targets.json").read_text("utf-8"))
GPU = next(t for t in TARGETS if t["modelKey"] == "vga|RTX5070")
NOW = datetime(2026, 11, 20, 6, tzinfo=timezone.utc)


def payload(rows):
    return {"error_code": 0, "error_msg": "Success", "data": {"rows": rows}}


def listing(title="华硕 RTX 5070 12GB 全新显卡", mall="京东",
            url="https://jingfen.jd.com/detail/test-listing.html", price="4399.50"):
    return {"title": title, "mall_name": mall, "url": url, "page_price": price}


class HainaContractTests(unittest.TestCase):
    def test_strict_model_match_and_official_product_link(self):
        rows = [
            listing(),
            listing("RTX 5070 Ti 16GB 显卡", url="https://item.jd.com/12.html"),
            listing("RTX 5070 显卡支架", url="https://item.jd.com/13.html"),
            listing(url="https://jingfen.jd.com.evil.example/detail/a.html"),
            listing(mall="未知", url="https://item.jd.com/14.html"),
            listing(price="nan", url="https://item.jd.com/15.html"),
            listing("七彩虹 RTX 5070 12G 显卡", "天猫",
                    "https://detail.tmall.com/item.htm?id=99", "4999.00"),
        ]
        offers = parse_haina_response(payload(rows), GPU, NOW)
        self.assertEqual(len(offers), 2)
        self.assertEqual({item["platform"] for item in offers}, {"京东", "天猫"})
        for offer in offers:
            self.assertEqual(offer["source"], "SMZDM Haina product search API")
            self.assertEqual(offer["priceType"], "retail-page-listed")
            self.assertEqual(offer["idType"], "source-listing-url")
            self.assertTrue(offer["skuId"].startswith("url-"))
            self.assertEqual(len(offer["skuId"]), 28)
        self.assertEqual(offers[0]["priceCents"], 439950)
        self.assertEqual(offers[0]["price"], 4400)

    def test_error_response_and_schema_must_fail_closed(self):
        with self.assertRaises(ValueError):
            parse_haina_response({"error_code": 403}, GPU, NOW)
        with self.assertRaises(ValueError):
            parse_haina_response({"error_code": 0, "data": {"rows": {}}}, GPU, NOW)
        self.assertEqual(parse_haina_response(payload([]), GPU, NOW), [])

    def test_build_feed_does_not_fabricate_historical_points(self):
        offers = parse_haina_response(payload([listing()]), GPU, NOW)
        feed = build_feed({GPU["modelKey"]: offers}, [GPU], NOW, provider="haina")
        self.assertEqual(feed["models"][0]["history"], [])
        self.assertEqual(feed["models"][0]["skuCount"], 1)
        updated = record_daily_history(feed, NOW)
        self.assertEqual(updated["models"][0]["history"],
                         [{"d": "2026-11-20", "median": 4400}])

    def test_history_only_real_days_and_same_source(self):
        offers = parse_haina_response(payload([listing()]), GPU, NOW)
        feed = build_feed({GPU["modelKey"]: offers}, [GPU], NOW, provider="haina")
        prior = {
            "sourceUrl": feed["sourceUrl"],
            "models": [{"modelKey": GPU["modelKey"], "history": [
                {"d": "2026-11-16", "median": 4300},
                {"d": "2026-11-18", "median": 4450},
                {"d": "2026-11-20", "median": 1},
                {"d": "2026-11-21", "median": 4000},
                {"d": "invalid", "median": 4000},
            ]}],
        }
        record_daily_history(feed, NOW, prior)
        self.assertEqual(feed["models"][0]["history"], [
            {"d": "2026-11-16", "median": 4300},
            {"d": "2026-11-18", "median": 4450},
            {"d": "2026-11-20", "median": 4400},
        ])
        self.assertEqual(feed["models"][0]["historyDays"], 3)

    def test_unrelated_source_history_not_mixed(self):
        feed = build_feed({GPU["modelKey"]: parse_haina_response(
            payload([listing()]), GPU, NOW)}, [GPU], NOW, provider="haina")
        previous = {"sourceUrl": "https://vramglass.com/",
                    "models": [{"modelKey": GPU["modelKey"],
                                "history": [{"d": "2026-11-19", "median": 30}]}]}
        record_daily_history(feed, NOW, previous)
        self.assertEqual(len(feed["models"][0]["history"]), 1)

    def test_missing_approval_never_queries_or_writes(self):
        env = {key: val for key, val in os.environ.items() if key not in {
            "MARKET_SMOKE_TEST", "MARKET_PUBLISH_ENABLED", "HAINA_API_KEY",
            "HJK_API_KEY", "TBK_APP_KEY", "TBK_APP_SECRET", "TBK_ADZONE_ID"}}
        env["MARKET_PROVIDER"] = "haina"
        process = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "fetch_market.py")],
            env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(process.returncode, 0)
        self.assertIn("not approved", process.stdout)


if __name__ == "__main__":
    unittest.main()
