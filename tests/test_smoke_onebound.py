import unittest
from datetime import date

from scripts.smoke_onebound import summarize


class OneboundSmokeSummaryTests(unittest.TestCase):
    def setUp(self):
        self.sku = "100147630258"
        self.model = "9800X3D"
        self.today = date(2026, 11, 21)

    def test_current_dated_series(self):
        payload = {
            "error_code": "0000",
            "items": {
                "num_iid": self.sku,
                "title": "AMD 9800X3D 盒装处理器",
                "item": [
                    {"date": "2026-10-01", "price": "2988"},
                    {"date": "2026-10-02", "price": "2899"},
                    {"date": "2026-11-20", "price": "2788"},
                ],
            },
        }
        summary = summarize(payload, self.sku, self.model, today=self.today)
        self.assertEqual(summary["status"], "usable_candidate")
        self.assertEqual(summary["price_points"], 3)
        self.assertEqual(summary["recent_90d_dates"], 3)
        self.assertTrue(summary["varying_prices"])

    def test_old_demo_is_not_usable(self):
        payload = {
            "error_code": "0000",
            "items": {
                "num_iid": self.sku,
                "title": "AMD 9800X3D",
                "item": [{"date": "2021-03-02", "price": "100"}],
            },
        }
        summary = summarize(payload, self.sku, self.model, today=self.today)
        self.assertEqual(summary["status"], "stale_or_sparse")
        self.assertEqual(summary["recent_90d_dates"], 0)

    def test_error_message_does_not_leak_key(self):
        payload = {
            "error_code": "4005",
            "reason": "key[secret-value] 或密钥错误",
            "error": "secret-value",
        }
        summary = summarize(payload, self.sku, self.model, today=self.today)
        self.assertEqual(summary["error_code"], "4005")
        self.assertNotIn("secret-value", repr(summary))

    def test_unrelated_product_is_rejected(self):
        payload = {
            "error_code": "0000",
            "items": {
                "num_iid": self.sku,
                "title": "AMD 9600X CPU",
                "item": [{"date": "2026-11-20", "price": "1200"}],
            },
        }
        summary = summarize(payload, self.sku, self.model, today=self.today)
        self.assertEqual(summary["status"], "model_mismatch")

    def test_gpu_spaces_in_title_are_ignored(self):
        payload = {
            "error_code": "0000",
            "items": {
                "num_iid": "100148892719",
                "title": "战斧 GeForce RTX5070Ti 豪华版 16GB",
                "item": [
                    {"date": "2026-10-19", "price": "6000"},
                    {"date": "2026-10-20", "price": "5900"},
                    {"date": "2026-11-20", "price": "5700"},
                ],
            },
        }
        summary = summarize(payload, "100148892719", "5070 Ti", today=self.today)
        self.assertEqual(summary["status"], "usable_candidate")

    def test_future_or_invalid_price_not_counted(self):
        payload = {
            "error_code": "0000",
            "items": {
                "num_iid": self.sku,
                "title": "AMD 9800X3D CPU",
                "item": [
                    {"date": "2026-11-22", "price": "3000"},
                    {"date": "2026-11-20", "price": "0"},
                    {"date": "2026-11-19", "price": "1299"},
                ],
            },
        }
        summary = summarize(payload, self.sku, self.model, today=self.today)
        self.assertEqual(summary["price_points"], 3)
        self.assertEqual(summary["valid_points"], 1)


if __name__ == "__main__":
    unittest.main()
