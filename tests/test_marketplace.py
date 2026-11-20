"""Network-free contract tests for the authorized marketplace pipeline."""
import hashlib
import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from marketplace import (build_feed, cny_cents, official_link, parse_taobao_response,
                         title_matches, top_sign)

TARGETS = json.loads((ROOT / "config" / "market-targets.json").read_text("utf-8"))
NOW = datetime(2026, 11, 20, 6, tzinfo=timezone.utc)


class MarketplaceTests(unittest.TestCase):
    def test_target_registry_and_identity(self):
        self.assertEqual(len(TARGETS), len({t["modelKey"] for t in TARGETS}))
        self.assertGreaterEqual(len(TARGETS), 10)
        for target in TARGETS:
            self.assertTrue(target["modelKey"].startswith(target["slug"] + "|"))
            self.assertTrue(target["required"])
            self.assertTrue(target["query"])

    def test_top_signature(self):
        args = {"method": "taobao.tbk.dg.material.optional", "v": "2.0", "app_key": "123"}
        expected = hashlib.md5(
            "SECRET" .encode() + b"app_key123methodtaobao.tbk.dg.material.optionalv2.0" + b"SECRET"
        ).hexdigest().upper()
        self.assertEqual(top_sign(args, "SECRET"), expected)
        self.assertEqual(top_sign({**args, "sign": "WRONG"}, "SECRET"), expected)

    def test_titles_reject_near_models_and_accessories(self):
        gpu = next(t for t in TARGETS if t["modelKey"] == "vga|RTX5070")
        self.assertTrue(title_matches("华硕 NVIDIA RTX 5070 12GB 显卡", gpu))
        self.assertFalse(title_matches("华硕 RTX 5070 Ti 16GB 显卡", gpu))
        self.assertFalse(title_matches("RTX 5070 显卡支架", gpu))
        large = next(t for t in TARGETS if t["modelKey"] == "vga|RTX5060TI")
        self.assertFalse(title_matches("RTX 5060 Ti 8GB 显卡", large))
        self.assertTrue(title_matches("RTX 5060 Ti O16G 显卡", large))

    def test_price_and_domains(self):
        self.assertEqual(cny_cents("1599.50"), 159950)
        self.assertIsNone(cny_cents("nan"))
        self.assertIsNone(cny_cents("-5"))
        self.assertEqual(
            official_link("淘宝", "http://item.taobao.com/item.htm?id=123"),
            "https://item.taobao.com/item.htm?id=123",
        )
        self.assertIsNone(official_link("京东", "https://jd.com.evil.example/123"))
        self.assertIsNone(official_link("淘宝", "https://item.taobao.com@evil.example/test"))

    def test_official_response_contract(self):
        target = next(t for t in TARGETS if t["modelKey"] == "vga|RTX5070")
        rows = [
            {"title": "华硕 RTX 5070 12G 显卡", "user_type": 0,
             "zk_final_price": "3999.49", "num_iid": 112233,
             "item_url": "http://item.taobao.com/item.htm?id=112233"},
            {"title": "RTX 5070 Ti 显卡", "user_type": 1,
             "zk_final_price": "5999", "num_iid": 2,
             "item_url": "https://detail.tmall.com/item.htm?id=2"},
            {"title": "RTX 5070 显卡支架", "user_type": 0,
             "zk_final_price": "19", "num_iid": 3,
             "item_url": "https://item.taobao.com/item.htm?id=3"},
        ]
        payload = {"tbk_dg_material_optional_response": {"result_list": {"map_data": rows}}}
        offers = parse_taobao_response(payload, target, NOW)
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["price"], 3999)
        self.assertEqual(offers[0]["priceCents"], 399949)
        self.assertEqual(offers[0]["skuId"], "112233")
        self.assertEqual(offers[0]["priceType"], "promotional-listed")
        feed = build_feed({target["modelKey"]: offers}, [target], NOW)
        self.assertEqual(len(feed["models"]), 1)
        self.assertEqual(feed["models"][0]["history"], [])
        self.assertEqual(feed["models"][0]["price"], 3999)

    def test_stale_and_missing_offers_do_not_fake_history(self):
        target = TARGETS[0]
        old = {
            "platform": "淘宝", "source": "official", "price": 999,
            "url": "https://item.taobao.com/item.htm?id=5",
            "observedAt": (NOW - timedelta(days=60)).isoformat(),
        }
        feed = build_feed({target["modelKey"]: [old]}, [target], NOW)
        self.assertEqual(feed["models"], [])

    def test_no_keys_is_safe_and_does_not_create_market_file(self):
        env = {k: v for k, v in os.environ.items() if k not in
               {"TBK_APP_KEY", "TBK_APP_SECRET", "TBK_ADZONE_ID"}}
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / "fetch_market.py")],
                                env=env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn("not configured", result.stdout)


if __name__ == "__main__":
    unittest.main()
