import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import deliverables as D
import geolib as G


class DeliverablesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.original_work = G.WORK
        G.WORK = Path(self.tmp.name)
        self.addCleanup(setattr, G, "WORK", self.original_work)
        self.pdir = G.project_dir("demo")
        self.pdir.mkdir()
        (self.pdir / "geo.json").write_text(json.dumps({
            "brand": {"name": "Acme", "site": "https://acme.example", "disambiguation": []},
            "market": "global", "targets": {},
        }), "utf-8")
        G.write_json(self.pdir / "audit.json", {
            "avg_score": 70, "page_count": 1, "grade_distribution": {"B": 1},
            "site": {"has_sitemap": True, "has_llms_txt": True, "ai_bots_blocked": []},
            "pages": [{"url": "https://acme.example", "score": 70, "word_count": 500,
                       "issue_codes": [], "blocks": {}}], "block_gap": [],
        })
        G.write_json(self.pdir / "tasks.json", {"tasks": [], "summary": {
            "total": 0, "by_priority": {}, "by_status": {}, "auto_verifiable": 0,
        }})

    def test_weighted_average_uses_sample_counts(self):
        self.assertAlmostEqual(D._weighted([
            {"samples": 1, "mention_rate": 1.0},
            {"samples": 9, "mention_rate": 0.0},
            {"samples": 0, "mention_rate": 1.0},
        ], "mention_rate"), 0.1)
        self.assertIsNone(D._weighted([], "mention_rate"))

    def test_run_builds_strategy_and_execution_without_prior_report(self):
        output = D.run("demo")
        self.assertEqual(output, self.pdir / "deliverables")
        expected = {
            "2-GEO-Optimization-Plan.md", "2-GEO-Optimization-Plan.html",
            "3-GEO-Execution-Plan.md", "3-GEO-Execution-Plan.html",
        }
        self.assertTrue(expected.issubset({path.name for path in output.iterdir()}))
        self.assertIn("Acme", (output / "2-GEO-Optimization-Plan.md").read_text("utf-8"))

    def test_latest_metrics_snapshot_is_used(self):
        G.write_json(self.pdir / "metrics" / "2026-01-01.json", {"platforms": {
            "p": {"market": "global", "samples": 10, "mention_rate": 0.1,
                  "own_domain_cite_rate": 0.2},
        }})
        G.write_json(self.pdir / "metrics" / "2026-02-01.json", {"platforms": {
            "p": {"market": "global", "samples": 10, "mention_rate": 0.7,
                  "own_domain_cite_rate": 0.6},
        }})
        plan = D.optimization_plan("demo")
        self.assertIn("mention rate 70%", plan)
        self.assertIn("citation rate 60%", plan)


if __name__ == "__main__":
    unittest.main()
