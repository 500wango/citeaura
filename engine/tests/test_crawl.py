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
        target = (G.urlparse("http://x.test/"), ("93.184.216.34",))
        with mock.patch.object(G, "_request_pinned", side_effect=responses) as get, \
             mock.patch.object(G, "_validate_fetch_target", return_value=target), \
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

    def test_prefers_main_over_later_article_cards(self):
        body = """<html><body>
        <header class="site-header"><h1>Chrome</h1></header>
        <main><h1>Win brand visibility</h1><h2>Workflow</h2><p>Body copy.</p>
        <article class="price-card"><p>Starter</p></article></main>
        </body></html>"""
        page = crawl.analyze_page("https://example.com/", {
            "html": body, "final_url": "https://example.com/", "status": 200, "error": None,
        })
        self.assertEqual(page["h1"], ["Win brand visibility"])
        self.assertEqual(page["h2"], ["Workflow"])

    def test_keeps_h1_inside_article_and_legal_header_classes(self):
        blog = """<html><body><article class="blog-article">
        <header class="blog-header"><h1>Why ChatGPT does not mention my brand</h1></header>
        <h2>Common reasons</h2><p>Explanation.</p></article></body></html>"""
        legal = """<html><body><main class="legal-content">
        <div class="legal-header"><h1>Privacy Policy</h1></div>
        <h2>Overview</h2><p>Policy body.</p></main></body></html>"""
        blog_page = crawl.analyze_page("https://example.com/blog/x", {
            "html": blog, "final_url": "https://example.com/blog/x", "status": 200, "error": None,
        })
        legal_page = crawl.analyze_page("https://example.com/privacy", {
            "html": legal, "final_url": "https://example.com/privacy", "status": 200, "error": None,
        })
        self.assertEqual(blog_page["h1"], ["Why ChatGPT does not mention my brand"])
        self.assertEqual(legal_page["h1"], ["Privacy Policy"])

    def test_multiple_h1s_in_main_remain_visible(self):
        body = """<html><body><main>
        <h1>First</h1><h1>Second</h1><h2>Section</h2><p>Copy.</p>
        </main></body></html>"""
        page = crawl.analyze_page("https://example.com/x", {
            "html": body, "final_url": "https://example.com/x", "status": 200, "error": None,
        })
        self.assertEqual(page["h1"], ["First", "Second"])

    def test_select_candidates_skips_llms_txt(self):
        selected = crawl.select_candidates(
            ["https://example.com/llms.txt", "https://example.com/docs", "https://example.com/pricing"],
            "https://example.com",
            8,
        )
        self.assertNotIn("https://example.com/llms.txt", selected)
        self.assertIn("https://example.com/docs", selected)

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
        with mock.patch.object(G, "fetch_text", side_effect=lambda url, timeout=8, allow_machine_file=False: payloads.get(url, "")) as fetch:
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


class AutoPageLimitTest(unittest.TestCase):
    """写死页数会让中大站点的页面级审计只覆盖不到一成，必须按站点规模分档。"""

    def test_small_sites_are_crawled_in_full(self):
        self.assertEqual(crawl.auto_page_limit(0), 25)
        self.assertEqual(crawl.auto_page_limit(18), 18)
        self.assertEqual(crawl.auto_page_limit(40), 40)

    def test_large_sites_get_a_bounded_quota(self):
        self.assertEqual(crawl.auto_page_limit(41), 60)
        self.assertEqual(crawl.auto_page_limit(150), 60)
        self.assertEqual(crawl.auto_page_limit(151), 100)
        self.assertEqual(crawl.auto_page_limit(500), 100)
        self.assertEqual(crawl.auto_page_limit(501), 120)
        self.assertEqual(crawl.auto_page_limit(5000), 120)

    def test_explicit_limit_wins_over_config(self):
        cfg = {"pages": {"max": 40}}
        self.assertEqual(crawl.resolve_page_limit(cfg, 7, 300), (7, "explicit"))
        self.assertEqual(crawl.resolve_page_limit(cfg, None, 300), (40, "config"))

    def test_legacy_default_config_is_upgraded(self):
        """存量项目里的 25 是旧版 init 写死的默认值，继续沿用等于改造没生效。"""
        legacy = {"pages": {"max": crawl.LEGACY_DEFAULT_PAGE_LIMIT}}
        self.assertEqual(crawl.resolve_page_limit(legacy, None, 900), (120, "auto"))
        self.assertEqual(crawl.resolve_page_limit(legacy, 12, 900), (12, "explicit"))

    def test_unset_config_falls_back_to_site_size(self):
        self.assertEqual(crawl.resolve_page_limit({"pages": {"max": None}}, None, 300), (100, "auto"))
        self.assertEqual(crawl.resolve_page_limit({}, None, 10), (10, "auto"))

    def test_run_records_crawl_coverage(self):
        """覆盖率必须落盘：报告和界面靠它区分全站抓取与抽样。"""
        with tempfile.TemporaryDirectory() as d:
            old_work = G.WORK
            G.WORK = Path(d)
            try:
                pdir = G.project_dir("demo")
                pdir.mkdir(parents=True, exist_ok=True)
                (pdir / "geo.json").write_text(json.dumps({
                    "brand": {"site": "https://example.com"}, "market": "global",
                    "pages": {"seed": [], "max": None},
                }), "utf-8")
                locs = [f"https://example.com/p/{i}" for i in range(5)]
                sitemap = "<urlset>" + "".join(f"<url><loc>{url}</loc></url>" for url in locs) + "</urlset>"
                texts = {"https://example.com/sitemap.xml": sitemap}
                ok = {"status": 200, "final_url": "https://example.com/", "error": None,
                      "html": "<html><body><main><h1>Title</h1><p>Body text</p></main></body></html>"}
                with mock.patch.object(G, "fetch_text", side_effect=lambda url, **kw: texts.get(url, "")), \
                     mock.patch.object(G, "fetch", return_value=ok):
                    site = crawl.run("demo", delay=0)
                self.assertEqual(site["coverage"]["discovered_urls"], 5)
                self.assertEqual(site["coverage"]["crawled_pages"], site["pages_crawled"])
                self.assertEqual(site["coverage"]["ratio"], 1.0)
                self.assertEqual(site["coverage"]["mode"], "full")
                self.assertEqual(site["coverage"]["limit_source"], "auto")
            finally:
                G.WORK = old_work


class TestCrawlRedirectPolicy(unittest.TestCase):
    def test_blocked_redirect_is_not_fetched(self):
        response = FakeResp(302)
        response.headers['Location'] = '/private'
        target = (G.urlparse('http://x.test/'), ('93.184.216.34',))
        robots = 'User-agent: CiteAuraEngine\nDisallow: /private\n\nUser-agent: *\nAllow: /\n'
        with mock.patch.object(G, '_request_pinned', return_value=response) as request, \
             mock.patch.object(G, '_validate_fetch_target', return_value=target):
            result = G.fetch('http://x.test/', retries=0, redirect_policy=lambda url: not
                             crawl.robots_disallows(robots, 'CiteAuraEngine', G.urlparse(url).path))
        self.assertEqual(result['status'], 0)
        self.assertEqual(result['final_url'], 'http://x.test/private')
        self.assertEqual(request.call_count, 1)

    def test_subdomain_uses_own_robots_policy(self):
        with tempfile.TemporaryDirectory() as d:
            old_work = G.WORK
            G.WORK = Path(d)
            try:
                pdir = G.project_dir("demo")
                pdir.mkdir(parents=True)
                (pdir / "geo.json").write_text(json.dumps({
                    "brand": {"site": "https://example.com"}, "market": "global",
                    "pages": {"seed": ["https://docs.example.com/private"], "max": 5},
                }), "utf-8")
                robots = {"https://docs.example.com/robots.txt":
                          "User-agent: CiteAuraEngine\nDisallow: /private\n"}
                calls = []
                def fetch(url, **kwargs):
                    calls.append(url)
                    return {"url": url, "final_url": url, "status": 200, "error": None,
                            "html": "<html><body>ok</body></html>"}
                with mock.patch.object(G, "fetch_text", side_effect=lambda url, **kw: robots.get(url, "")) as text, \
                     mock.patch.object(G, "fetch", side_effect=fetch):
                    crawl.run("demo", delay=0)
                self.assertNotIn("https://docs.example.com/private", calls)
                self.assertIn("https://docs.example.com/robots.txt", [c.args[0] for c in text.call_args_list])
            finally:
                G.WORK = old_work


if __name__ == "__main__":
    unittest.main()
