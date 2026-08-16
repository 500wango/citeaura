import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import geolib as G
import crawl


class FakeResp:
    """模拟 requests.get 的流式响应，够 fetch 用即可。"""

    def __init__(self, status, body=b"<html>ok</html>", ctype="text/html"):
        self.status_code = status
        self.headers = {"Content-Type": ctype}
        self.url = "http://x.test/"
        self._body = body
        self.encoding = "utf-8"

    def iter_content(self, n):
        yield self._body

    def close(self):
        pass


class TestFetchRetry(unittest.TestCase):
    def _run(self, responses, retries=1):
        with mock.patch.object(G.requests, "get", side_effect=responses) as get, \
             mock.patch.object(G, "_validate_fetch_target"), \
             mock.patch.object(G.time, "sleep"):
            res = G.fetch("http://x.test/", retries=retries)
        return res, get.call_count

    def test_retry_500_then_200(self):
        res, calls = self._run([FakeResp(500), FakeResp(200)])
        self.assertEqual(res["status"], 200)
        self.assertEqual(calls, 2)

    def test_retry_429(self):
        res, calls = self._run([FakeResp(429), FakeResp(200)])
        self.assertEqual(res["status"], 200)
        self.assertEqual(calls, 2)

    def test_no_retry_404(self):
        res, calls = self._run([FakeResp(404)])
        self.assertEqual(res["status"], 404)
        self.assertEqual(calls, 1)

    def test_retry_exhausted_returns_last(self):
        res, calls = self._run([FakeResp(500), FakeResp(500)])
        self.assertEqual(res["status"], 500)
        self.assertEqual(calls, 2)


class TestCrawlHealth(unittest.TestCase):
    def _pages(self, statuses):
        return [{"status": s} for s in statuses]

    def test_all_dead_dies(self):
        with self.assertRaises(SystemExit):
            crawl.check_crawl_health(self._pages([0, 0, 0]))

    def test_low_ok_ratio_dies(self):
        with self.assertRaises(SystemExit):
            crawl.check_crawl_health(self._pages([200] + [0] * 9))

    def test_healthy_passes(self):
        crawl.check_crawl_health(self._pages([200] * 5))
        crawl.check_crawl_health(self._pages([200] + [0] * 4))  # 20% 刚好达标

    def test_snapshot_pruning_keeps_latest_runs(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name in ("crawl-001", "crawl-002", "crawl-003"):
                (root / name).mkdir()
            removed = crawl._prune_snapshots(root, keep=2)
            self.assertEqual(removed, 1)
            self.assertFalse((root / "crawl-001").exists())
            self.assertTrue((root / "crawl-002").exists())
            self.assertTrue((root / "crawl-003").exists())


class TestWordCountKana(unittest.TestCase):
    def test_pure_kana_counts(self):
        self.assertGreater(G.word_count("これはテストです"), 0)

    def test_cjk_unchanged(self):
        self.assertGreater(G.word_count("这是一个测试"), 0)


class TestCrawlSelectionAndEvidence(unittest.TestCase):
    def test_main_dom_drives_structure_and_links(self):
        body = """<html><body><header><h1>Navigation</h1><ul><li>A</li><li>B</li></ul></header>
        <main><h1>Article</h1><h2>Section</h2><p>Useful body text.</p><a href="https://outside.test/x">Source</a></main>
        <footer><p>Footer boilerplate</p></footer></body></html>"""
        page = crawl.analyze_page("https://example.com/a", {
            "html": body, "final_url": "https://example.com/a", "status": 200, "error": None,
        })
        self.assertEqual(page["h1"], ["Article"])
        self.assertEqual(page["li_count"], 0)
        self.assertEqual(page["para_count"], 1)
        self.assertEqual(page["external_links"], 1)

    def test_role_quota_limits_help_pages(self):
        urls = ([f"https://example.com/help/topic-{i}" for i in range(12)]
                + ["https://example.com/product", "https://example.com/pricing", "https://example.com/about"])
        selected = crawl.select_candidates(urls, "https://example.com", 8)
        self.assertLessEqual(sum(crawl.url_role(url) == "support" for url in selected), 2)
        self.assertIn("https://example.com/product", selected)

    def test_sitemap_rejects_cross_site_maps_and_urls(self):
        root = "https://example.com"
        payloads = {
            "https://example.com/robots.txt": "Sitemap: https://evil.test/map.xml\nSitemap: /good.xml",
            "https://example.com/sitemap.xml": "",
            "https://example.com/sitemap_index.xml": "",
            "https://example.com/good.xml": (
                "<urlset><url><loc>https://example.com/a</loc></url>"
                "<url><loc>https://evil.test/stolen</loc></url></urlset>"
            ),
        }
        with mock.patch.object(G, "fetch_text", side_effect=lambda url, timeout=8: payloads.get(url, "")) as fetch:
            urls = crawl.discover_sitemap(root)
        self.assertEqual(urls, ["https://example.com/a"])
        self.assertFalse(any(call.args[0].startswith("https://evil.test") for call in fetch.call_args_list))

    def test_robots_wildcard_and_specific_override(self):
        self.assertTrue(crawl.robots_disallows_root("User-agent: *\nDisallow: /*", "GPTBot"))
        policy = "User-agent: *\nDisallow: /\n\nUser-agent: GPTBot\nAllow: /"
        self.assertFalse(crawl.robots_disallows_root(policy, "GPTBot"))
        self.assertTrue(crawl.robots_disallows_root(policy, "ClaudeBot"))

    def test_failed_crawl_keeps_last_known_good_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            old_work = G.WORK
            G.WORK = Path(d)
            try:
                pdir = G.project_dir("demo")
                (pdir / "evidence").mkdir(parents=True)
                (pdir / "geo.json").write_text(json.dumps({
                    "brand": {"site": "https://example.com"}, "market": "global",
                    "pages": {"seed": [], "max": 1},
                }), "utf-8")
                G.write_json(pdir / "evidence" / "site.json", {"crawl_run_id": "good"})
                G.write_jsonl(pdir / "evidence" / "pages.jsonl", [{"url": "https://example.com", "status": 200}])
                failed = {"status": 0, "html": "", "final_url": "https://example.com", "error": "down"}
                with mock.patch.object(G, "fetch_text", return_value=""), mock.patch.object(G, "fetch", return_value=failed):
                    with self.assertRaises(SystemExit):
                        crawl.run("demo", max_pages=1, delay=0)
                self.assertEqual(G.read_json(pdir / "evidence" / "site.json")["crawl_run_id"], "good")
                self.assertEqual(G.read_jsonl(pdir / "evidence" / "pages.jsonl")[0]["status"], 200)
            finally:
                G.WORK = old_work


if __name__ == "__main__":
    unittest.main()
