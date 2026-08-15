import copy
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import benchmark as B


class BenchmarkTest(unittest.TestCase):
    def test_normalizes_and_aggregates_domain_variants(self):
        source = {
            "HTTPS://WWW.QQ.COM.:443/news": 2,
            "news.qq.com": 3,
            "qq.com": 4,
        }
        before = copy.deepcopy(source)
        result = B.compare(source)
        row = next(item for item in result["cross_platform_covered"] if item["domain"] == "qq.com")
        self.assertEqual(row["your_citations"], 9)
        self.assertEqual(source, before)

    def test_ignores_invalid_and_non_positive_counts(self):
        result = B.compare({
            "qq.com": -1,
            "www.qq.com": True,
            "https://qq.com/x": math.nan,
            "": 20,
            "maigoo.com": "7",
        })
        covered = {item["domain"] for item in result["cross_platform_covered"]}
        self.assertNotIn("qq.com", covered)
        self.assertNotIn("maigoo.com", covered)

    def test_subdomain_hits_ecosystem_and_position_sets(self):
        result = B.compare({"m.sm.cn": 2, "guide.cnpp.cn": 1})
        gaps = {item["domain"] for item in result["ecosystem_gaps"]}
        self.assertNotIn("sm.cn", gaps)
        positions = {item["domain"]: item["your_citations"] for item in result["high_position_hits"]}
        self.assertEqual(positions, {"sm.cn": 2, "cnpp.cn": 1})


if __name__ == "__main__":
    unittest.main()
