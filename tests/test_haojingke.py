"""Offline contract fixtures based on HaoJingKe's documented field names.

These are NOT evidence of live API access, current prices or authorization to
republish responses. The production collector remains opt-in.
"""
import io
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from haojingke import (DOCUMENTED_ENDPOINTS, parse_haojingke_response,
                       query_haojingke)
from fetch_market import safe_provider_failure_category
from marketplace import build_feed

TARGETS = json.loads((ROOT / "config" / "market-targets.json").read_text("utf-8"))
GPU = next(t for t in TARGETS if t["modelKey"] == "vga|RTX5070")
NOW = datetime(2026, 11, 20, 8, tzinfo=timezone.utc)


class HaoJingKeTests(unittest.TestCase):
    def test_private_error_diagnostics_only_emit_fixed_categories(self):
        self.assertEqual(safe_provider_failure_category({
            "status_code": 1, "data": "京东联盟未授权 key=FAKE_TEST_VALUE"
        }), "authorization")
        self.assertEqual(safe_provider_failure_category({
            "status_code": 1, "message": "apiKey invalid FAKE_TEST_VALUE"
        }), "credential")
        self.assertEqual(safe_provider_failure_category({
            "status_code": 1, "message": "FAKE_TEST_VALUE"
        }), "unknown")

    def test_jd_uses_original_reference_not_conditional_coupon(self):
        payload = {"status_code": 200, "data": {"data": [
            {"goods_id": "123456789", "goods_name": "华硕 RTX 5070 12GB 显卡",
             "materiaurl": "item.jd.com/123456789.html",
             "price": "3999.95", "price_after": "3499.99"},
            {"goods_id": "2", "goods_name": "RTX 5070 Ti 显卡",
             "materiaurl": "https://item.jd.com/2.html", "price": "5999"},
            {"goods_id": "3", "goods_name": "RTX 5070 显卡供电线",
             "materiaurl": "https://item.jd.com/3.html", "price": "19.9"},
            {"goods_id": "4", "goods_name": "RTX 5070 12GB 显卡",
             "materiaurl": "https://item.jd.com/9999.html", "price": "100"},
        ]}}
        offers = parse_haojingke_response(payload, GPU, NOW, "jd")
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["priceCents"], 399995)
        self.assertEqual(offers[0]["price"], 4000)
        self.assertEqual(offers[0]["conditionalCouponPriceCents"], 349999)
        self.assertEqual(offers[0]["priceType"], "original-reference")
        self.assertEqual(offers[0]["url"], "https://item.jd.com/123456789.html")

    def test_pdd_requires_real_goods_url_and_distinct_ids(self):
        payload = {"status_code": "200", "data": {"goods_list": [
            {"goods_id": 123456, "goods_name": "RTX 5070 12G 显卡",
             "materiaurl": "http://mobile.yangkeduo.com/goods2.html?goods_id=123456",
             "price": 4100, "price_after": 3990},
            {"goods_id": 123456, "goods_name": "RTX 5070 12G 显卡",
             "materiaurl": "https://mobile.yangkeduo.com/goods2.html?goods_id=123456",
             "price": 4100},
            {"goods_id": 222, "goods_name": "RTX 5070 12G 显卡",
             "materiaurl": "https://mobile.yangkeduo.com/goods2.html?goods_id=111",
             "price": 3000},
            {"goods_id": 333, "goods_name": "RTX 5070 Laptop GPU",
             "materiaurl": "https://mobile.yangkeduo.com/goods2.html?goods_id=333",
             "price": 3000},
        ]}}
        offers = parse_haojingke_response(payload, GPU, NOW, "pdd")
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["platform"], "拼多多")
        self.assertEqual(offers[0]["priceCents"], 410000)
        self.assertEqual(offers[0]["url"],
                         "https://mobile.yangkeduo.com/goods.html?goods_id=123456")

    def test_invalid_provider_responses_fail_closed(self):
        for payload in ({"status_code": 403, "data": {}},
                        {"status_code": 200, "data": None},
                        {"data": []}):
            with self.assertRaises(ValueError):
                parse_haojingke_response(payload, GPU, NOW, "jd")

    def test_cross_platform_feed_references_documented_source(self):
        jd = parse_haojingke_response({"status_code": 200, "data": {"data": [{
            "goods_id": "11", "goods_name": "RTX 5070 12G 显卡",
            "materiaurl": "https://item.jd.com/11.html", "price": "4200",
        }]}}, GPU, NOW, "jd")
        pdd = parse_haojingke_response({"status_code": 200, "data": {"goods_list": [{
            "goods_id": 22, "goods_name": "RTX 5070 12G 显卡",
            "materiaurl": "https://mobile.yangkeduo.com/goods2.html?goods_id=22",
            "price": "3800",
        }]}}, GPU, NOW, "pdd")
        feed = build_feed({GPU["modelKey"]: jd + pdd}, [GPU], NOW,
                          provider="haojingke")
        self.assertEqual(feed["models"][0]["price"], 4000)
        self.assertEqual(feed["models"][0]["skuCount"], 2)
        self.assertEqual(feed["models"][0]["history"], [])
        self.assertIn("haojingke.com", feed["sourceUrl"])

    def test_request_uses_https_post_body_without_following_redirects(self):
        class FakeResponse(io.BytesIO):
            def geturl(self):
                return DOCUMENTED_ENDPOINTS["jd"]

        class FakeOpener:
            def open(self, request, timeout):
                self.request = request
                self.timeout = timeout
                return FakeResponse(b'{"status_code":200,"data":{"data":[]}}')

        opener = FakeOpener()
        with patch("haojingke.urllib.request.build_opener", return_value=opener):
            result = query_haojingke("jd", GPU, "FAKE_TEST_KEY")
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(opener.request.get_method(), "POST")
        self.assertTrue(opener.request.full_url.startswith("https://"))
        self.assertNotIn("FAKE_TEST_KEY", opener.request.full_url)
        self.assertIn(b"FAKE_TEST_KEY", opener.request.data)
        params = parse_qs(opener.request.data.decode("utf-8"))
        self.assertEqual(params["pageindex"], ["1"])
        self.assertEqual(params["pagesize"], ["20"])
        self.assertEqual(params["iscoupon"], ["0"])
        self.assertNotIn("page_size", params)


if __name__ == "__main__":
    unittest.main()
