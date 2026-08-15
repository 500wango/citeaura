import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import blueprint as B
import geolib as G


class BlueprintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.original_work = G.WORK
        G.WORK = Path(self.tmp.name)
        self.addCleanup(setattr, G, "WORK", self.original_work)
        self.pdir = G.project_dir("demo")
        self.pdir.mkdir(parents=True)
        cfg = {
            "brand": {"name": "Acme", "site": "https://WWW.Acme.COM.:443/home"},
            "market": "both",
            "questions": [
                {"id": "q001", "market": "cn", "group": "recommendation", "text": "Ready?"},
                {"id": "q002", "market": "cn", "group": "comparison", "text": "Draft?"},
                {"id": "q003", "market": "global", "group": "risk", "text": "Outline?"},
                {"id": "q004", "market": "global", "group": "other", "text": "Gap?"},
            ],
        }
        (self.pdir / "geo.json").write_text(json.dumps(cfg), "utf-8")

    def _metrics(self, platforms):
        G.write_json(self.pdir / "metrics" / "2026-08-15.json", {"platforms": platforms})

    def test_brand_evidence_controls_coverage(self):
        self._metrics({
            "cn-observed": {"market": "cn", "top_cited_domains": {"news.qq.com": 2}},
            "cn-brand": {"market": "cn", "top_brand_cited_domains": {"https://mp.weixin.qq.com/a": 1}},
            "global-brand": {"market": "global", "top_brand_cited_domains": {"blog.acme.com": 1}},
        })
        result = B.build("demo")
        channels = {(row["market"], row["id"]): row for row in result["channels"]}
        wechat = channels[("cn", "wechat")]
        self.assertTrue(wechat["covered"])
        self.assertEqual(wechat["coverage_status"], "brand_cited")
        self.assertIn("news.qq.com", wechat["observed_source_evidence"])
        self.assertTrue(channels[("global", "official_en")]["covered"])

    def test_observed_source_is_not_treated_as_brand_coverage(self):
        self._metrics({"cn": {"market": "cn", "top_cited_domains": {"qq.com": 1}}})
        result = B.build("demo")
        wechat = next(row for row in result["channels"] if row["id"] == "wechat")
        self.assertFalse(wechat["covered"])
        self.assertEqual(wechat["coverage_status"], "observed_source")

    def test_unknown_metric_market_is_ignored(self):
        self._metrics({"legacy": {"market": "mars", "top_cited_domains": {"qq.com": 1}}})
        result = B.build("demo")
        self.assertEqual(result["coverage"]["channel_covered"], 0)

    def test_content_status_precedence(self):
        for directory, qid in (("content", "q001"), ("assets/drafts", "q002"),
                               ("assets/outlines", "q003")):
            target = self.pdir / directory
            target.mkdir(parents=True, exist_ok=True)
            (target / f"{qid}.md").write_text(f"# {qid}\n", "utf-8")
        (self.pdir / "assets" / "drafts" / "q001.md").write_text("# q001\n", "utf-8")
        result = B.build("demo")
        statuses = {row["id"]: row["status"] for row in result["contents"]}
        self.assertEqual(statuses, {"q001": "ready", "q002": "draft", "q003": "outline_only", "q004": "gap"})


if __name__ == "__main__":
    unittest.main()
