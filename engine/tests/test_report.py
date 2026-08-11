import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import report as R

CFG = {"brand": {"name": "Acme", "site": "https://www.acme.com"}, "market": "both"}

AUDIT = {
    "page_count": 10, "avg_score": 60,
    "site": {"has_sitemap": True, "sitemap_url_count": 5, "has_llms_txt": False,
             "ai_bots_blocked": [], "pages_ok": 10, "pages_crawled": 10},
    "site_issues": [], "language_coverage": {},
    "grade_distribution": {"A": 2, "B": 4, "C": 3, "D": 1},
    "pages": [], "block_gap": [],
}


def plat(market, mention, label=None):
    d = {"market": market, "mention_rate": mention, "samples": 5,
         "top1_rate": 0.0, "top3_rate": 0.0, "avg_rank": None,
         "own_domain_cite_rate": None, "probe": {},
         "competitor_mentions": {}, "top_cited_domains": {}}
    if label:
        d["label"] = label
    return d


def metrics_with(platforms):
    return {"date": "2026-07-27", "sample_count": 20, "question_count": 5,
            "platforms": platforms}


def md(platforms):
    return R.build_markdown(CFG, AUDIT, metrics_with(platforms), None, None, [])


class TestBestWorstDegenerate(unittest.TestCase):
    def test_all_zero_no_conclusion(self):
        m = md({"qwen": plat("cn", 0.0, "Qwen"), "deepseek": plat("cn", 0.0, "DeepSeek"),
                "perplexity": plat("global", 0.0, "Perplexity")})
        self.assertIn("Uniform mention rates", m)
        self.assertNotIn("Top Performer", m)
        self.assertNotIn("Weakest", m)

    def test_single_platform_no_conclusion(self):
        m = md({"qwen": plat("cn", 0.5, "Qwen")})
        self.assertIn("Uniform mention rates", m)
        self.assertNotIn("Top Performer", m)
        self.assertNotIn("Weakest", m)

    def test_all_equal_no_conclusion(self):
        m = md({"qwen": plat("cn", 0.3, "Qwen"), "deepseek": plat("cn", 0.3, "DeepSeek")})
        self.assertIn("Uniform mention rates", m)
        self.assertNotIn("Top Performer", m)
        self.assertNotIn("Weakest", m)

    def test_normal_two_platforms_conclusion(self):
        m = md({"qwen": plat("cn", 0.5, "Qwen"), "deepseek": plat("cn", 0.1, "DeepSeek")})
        self.assertIn("Top Performer", m)
        self.assertIn("Weakest", m)
        self.assertIn("Qwen", m)
        self.assertIn("DeepSeek", m)
        self.assertNotIn("Uniform mention rates", m)

    def test_none_filtered_then_single_no_conclusion(self):
        m = md({"qwen": plat("cn", 0.5, "Qwen"), "deepseek": plat("cn", None, "DeepSeek")})
        self.assertIn("Uniform mention rates", m)
        self.assertNotIn("Top Performer", m)

    def test_all_none_market_untested(self):
        m = md({"qwen": plat("cn", 0.5, "Qwen"), "deepseek": plat("cn", 0.1, "DeepSeek"),
                "perplexity": plat("global", None, "Perplexity")})
        self.assertIn("Global: Unmeasured", m)
        self.assertIn("Domestic (CN) Top Performer", m)


class TestMarketAvgCards(unittest.TestCase):
    def test_split_cn_global(self):
        cards = dict(R.market_avg_cards(metrics_with({
            "qwen": plat("cn", 0.5), "deepseek": plat("cn", 0.5),
            "perplexity": plat("global", 0.1)})))
        self.assertEqual(cards["Domestic (CN) Avg Mention"], "50%")
        self.assertEqual(cards["Global Avg Mention"], "10%")

    def test_none_market_untested(self):
        cards = dict(R.market_avg_cards(metrics_with({
            "qwen": plat("cn", 0.5), "perplexity": plat("global", None)})))
        self.assertEqual(cards["Domestic (CN) Avg Mention"], "50%")
        self.assertEqual(cards["Global Avg Mention"], "Unmeasured")

    def test_no_metrics_no_cards(self):
        self.assertEqual(R.market_avg_cards(None), [])


if __name__ == "__main__":
    unittest.main()
