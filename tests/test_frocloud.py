"""Offline tests for attributed, historical *monthly* community prices."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from fetch_frocloud import FILES, build_feed, model_identity, parse_csv, validate_feed

HEADER = "date,category,model,spec,price_cny,channel,note\n"


class FrocloudTests(unittest.TestCase):
    def fixture(self):
        return {
            "cpu-prices.csv": HEADER +
                "2025-01,CPU,R79800X3D,,4398,,\n2025-02,CPU,R79800X3D,,3999,,\n",
            "gpu-prices.csv": HEADER +
                "2025-01,显卡,5070Ti,Blackwell,6199,,\n" +
                "2026-07-下旬,显卡,5070Ti,Blackwell,7299,,7 月下半月快照\n",
            "memory-prices.csv": HEADER +
                "2026-06,内存 DDR5,内存,16G×2,53.72,,\n",
        }

    def test_month_precision_and_partial_month_retained_separately(self):
        feed = build_feed(self.fixture(), min_models=3)
        self.assertEqual(feed["source"], "FrocloudMonthly")
        self.assertEqual(feed["timeGrain"], "month")
        self.assertEqual(feed["license"], "CC BY 4.0")
        self.assertEqual(feed["dataThrough"], "2026-06")
        cpu = next(x for x in feed["models"] if x["slug"] == "cpu")
        self.assertEqual(cpu["modelKey"], "cpu|RYZEN79800X3D")
        self.assertEqual(cpu["history"], [
            {"month": "2025-01", "priceCny": "4398"},
            {"month": "2025-02", "priceCny": "3999"},
        ])
        gpu = next(x for x in feed["models"] if x["slug"] == "vga")
        self.assertEqual(gpu["modelKey"], "vga|RTX5070TI")
        self.assertEqual(len(gpu["history"]), 1)
        self.assertEqual(feed["specialSnapshots"][0]["month"], "2026-07-下旬")

    def test_per_gb_is_not_a_component_price(self):
        feed = build_feed(self.fixture(), min_models=3)
        ram = next(x for x in feed["models"] if x["slug"] == "memory")
        self.assertEqual(ram["unit"], "CNY/GB")
        self.assertEqual(ram["latestPriceCny"], "53.72")

    def test_gpu_variants_are_distinct(self):
        a = model_identity("显卡", "5060Ti8G", "")
        b = model_identity("显卡", "5060Ti16G", "")
        self.assertNotEqual(a[0], b[0])
        self.assertEqual(b[0], "vga|RTX5060TI16GB")

    def test_duplicate_period_rejected(self):
        sources = self.fixture()
        sources["cpu-prices.csv"] += "2025-01,CPU,R79800X3D,,4300,,\n"
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            build_feed(sources, min_models=3)

    def test_negative_nonfinite_and_zero_rejected(self):
        for bad in ("0", "-1", "NaN", "Infinity", "not-a-price"):
            with self.subTest(price=bad):
                sources = self.fixture()
                sources["cpu-prices.csv"] = sources["cpu-prices.csv"].replace("4398", bad)
                with self.assertRaises(ValueError):
                    build_feed(sources, min_models=3)

    def test_month_is_not_an_invented_calendar_day(self):
        rows = parse_csv("cpu-prices.csv", self.fixture()["cpu-prices.csv"])
        self.assertEqual(rows[0]["month"], "2025-01")
        self.assertNotIn("date", rows[0])

    def test_invalid_csv_format_rejected(self):
        with self.assertRaisesRegex(ValueError, "columns"):
            parse_csv("cpu-prices.csv", "date,model,price_cny\n2025-01,X,3\n")
        sources = self.fixture()
        sources["gpu-prices.csv"] = sources["gpu-prices.csv"].replace("2025-01", "2025-13")
        with self.assertRaisesRegex(ValueError, "period"):
            build_feed(sources, min_models=3)

    def test_requires_all_sources(self):
        with self.assertRaisesRegex(ValueError, "three"):
            build_feed({"cpu-prices.csv": self.fixture()["cpu-prices.csv"]})

    def test_production_validator_rejects_unknown_source(self):
        feed = build_feed(self.fixture(), min_models=3)
        feed["models"] = feed["models"] * 17  # enough entries to exercise identity check
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            validate_feed(feed)


if __name__ == "__main__":
    unittest.main()
