"""No-network tests for the pre-publication validation gate."""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_snapshot import validate


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "market.json"
        self.now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        self.body = {
            "source": "RetailAuthorized", "capturedAt": self.now,
            "models": [{
                "modelKey": "vga|RTX5090", "name": "RTX 5090",
                "price": 13999, "history": [],
                "offers": [{
                    "source": "Taobao Alliance TOP API", "platform": "淘宝",
                    "skuId": "10101", "title": "RTX 5090 32GB 显卡",
                    "url": "https://item.taobao.com/item.htm?id=10101",
                    "price": 13999, "priceCents": 1399900,
                    "observedAt": self.now,
                }],
            }]
        }

    def tearDown(self):
        self.temp.cleanup()

    def publish(self):
        self.path.write_text(json.dumps(self.body, ensure_ascii=False), "utf-8")
        return validate(self.path)

    def test_valid_retail_feed(self):
        self.assertEqual(self.publish()["offers"], 1)

    def test_reject_forged_domain(self):
        self.body["models"][0]["offers"][0]["url"] = "https://taobao.com.phishing.example/a"
        with self.assertRaisesRegex(ValueError, "provenance"):
            self.publish()

    def test_reject_wrong_model(self):
        self.body["models"][0]["offers"][0]["title"] = "RTX 5080 显卡"
        with self.assertRaisesRegex(ValueError, "model mismatch"):
            self.publish()

    def test_reject_price_precision_mismatch(self):
        self.body["models"][0]["offers"][0]["priceCents"] = 99900
        with self.assertRaisesRegex(ValueError, "cents precision"):
            self.publish()


if __name__ == "__main__":
    unittest.main()
