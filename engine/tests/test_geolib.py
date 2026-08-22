import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import geolib as G
import geo

class TestJsonIO(unittest.TestCase):
    def test_write_json_atomic(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            G.write_json(p, {"a": 1})
            self.assertEqual(G.read_json(p), {"a": 1})
            self.assertFalse(list(Path(d).glob("*.tmp")))

    def test_read_json_corrupt_returns_default(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            p.write_text("{broken", "utf-8")
            self.assertEqual(G.read_json(p, default={}), {})

    def test_concurrent_json_writes_use_distinct_atomic_temp_files(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            threads = [threading.Thread(target=G.write_json, args=(p, {"value": i}))
                       for i in range(12)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertIn(G.read_json(p)["value"], range(12))
            self.assertFalse(list(Path(d).glob("*.tmp")))

    def test_jsonl_skips_a_corrupt_interrupted_record(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.jsonl"
            p.write_text('{"ok": 1}\n{"truncated":\n{"ok": 2}\n', "utf-8")
            self.assertEqual(G.read_jsonl(p), [{"ok": 1}, {"ok": 2}])

    def test_project_dir_rejects_traversal(self):
        for bad in ("../x", "/etc", "a/b", ".."):
            with self.assertRaises(SystemExit):
                G.project_dir(bad)

    def test_project_dir_accepts_valid_slug(self):
        self.assertEqual(G.project_dir("aigclink"), G.WORK / "aigclink")

    def test_read_json_missing_returns_default(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "nope.json"
            self.assertEqual(G.read_json(p, default={"x": 1}), {"x": 1})
            self.assertIsNone(G.read_json(p))

    def test_project_lock_enter_exit(self):
        with tempfile.TemporaryDirectory() as d:
            slug = "locktest"
            orig_work = G.WORK
            G.WORK = Path(d)
            try:
                with G.project_lock(slug):
                    self.assertTrue((Path(d) / slug / ".lock").exists())
                self.assertTrue((Path(d) / slug / ".lock").exists())
            finally:
                G.WORK = orig_work

    def test_question_ids_are_safe_and_unique(self):
        rows = G.normalize_question_ids([
            {"id": "../../escaped", "text": "a"},
            {"id": "q101", "text": "b"},
            {"id": "q101", "text": "c"},
        ])
        self.assertEqual([row["id"] for row in rows], ["q001", "q101", "q002"])
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(G.safe_child(Path(d), "q001", ".md").parent, Path(d).resolve())
            with self.assertRaises(ValueError):
                G.safe_child(Path(d), "../../escaped", ".md")

    def test_relevance_tokens_split_chinese_intent(self):
        tokens = G.relevance_tokens("智能体平台怎么选？有哪些好用的替代品？")
        self.assertIn("智能体平台", tokens)
        self.assertIn("替代品", tokens)

    def test_normalize_host_accepts_urls_and_bare_domains(self):
        self.assertEqual(G.normalize_host(" HTTPS://User:pass@WWW.Example.COM.:443/a "), "example.com")
        self.assertEqual(G.normalize_host("www.example.com:8443/path"), "example.com")
        self.assertEqual(G.normalize_host("//sub.example.com/x"), "sub.example.com")
        self.assertEqual(G.normalize_host(""), "")
        self.assertEqual(G.normalize_host("http://[broken"), "")
        self.assertEqual(G.normalize_host("https://bad host.example"), "")

    def test_same_site_rejects_empty_hosts(self):
        self.assertFalse(G.same_site("", ""))
        self.assertTrue(G.same_site("https://www.example.com", "docs.example.com"))

    def test_fetch_target_rejects_private_resolution(self):
        with mock.patch.object(G.socket, "getaddrinfo", return_value=[(None, None, None, None, ("127.0.0.1", 80))]):
            with self.assertRaises(ValueError):
                G._validate_fetch_target("http://internal.example/")

    def test_machine_index_files_are_not_html_page_candidates(self):
        self.assertFalse(G.is_fetchable("https://example.com/llms.txt"))
        self.assertFalse(G.is_fetchable("https://example.com/llms.en.txt"))
        self.assertFalse(G.is_fetchable("https://example.com/robots.txt"))
        self.assertFalse(G.is_fetchable("https://example.com/sitemap.xml"))
        self.assertTrue(G.is_fetchable("https://example.com/docs"))
        self.assertTrue(G.is_fetchable("https://example.com/blog/what-to-put-in-llms-txt"))

    def test_normalize_url_rejects_non_http_and_malformed_links(self):
        self.assertIsNone(G.normalize_url("https://example.com", "javascript:alert(1)"))
        self.assertIsNone(G.normalize_url("https://example.com", "ftp://example.com/file"))
        self.assertIsNone(G.normalize_url("https://example.com", "http://[broken"))
        self.assertIsNone(G.normalize_url("https://example.com", "https://user:pass@example.com/private"))

    def test_fetch_text_uses_bounded_fetch_contract(self):
        with mock.patch.object(G, "fetch", return_value={"status": 200, "html": "robots"}) as fetch:
            self.assertEqual(G.fetch_text("https://example.com/robots.txt", timeout=3), "robots")
        fetch.assert_called_once_with("https://example.com/robots.txt", timeout=3, retries=0)

    def test_fetch_machine_file_requires_explicit_opt_in(self):
        response = mock.Mock(
            status_code=200,
            headers={"Content-Type": "text/plain; charset=utf-8"},
            url="https://example.com/robots.txt",
            encoding="utf-8",
        )
        response.iter_content.return_value = [b"User-agent: *\nDisallow: /private"]
        target = (G.urlparse("https://example.com/robots.txt"), ("93.184.216.34",))
        with mock.patch.object(G, "_request_pinned", return_value=response), \
             mock.patch.object(G, "_validate_fetch_target", return_value=target):
            skipped = G.fetch("https://example.com/robots.txt", retries=0)
            allowed = G.fetch("https://example.com/robots.txt", retries=0, allow_machine_file=True)
        self.assertEqual(skipped["status"], 0)
        self.assertEqual(allowed["status"], 200)
        self.assertIn("Disallow: /private", allowed["html"])

    def test_fetch_closes_stream_and_enforces_exact_byte_limit(self):
        response = mock.Mock(
            status_code=200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            url="https://example.com",
            encoding="utf-8",
        )
        response.iter_content.return_value = [b"a" * G.MAX_BYTES, b"overflow"]
        target = (G.urlparse("https://example.com"), ("93.184.216.34",))
        with mock.patch.object(G, "_request_pinned", return_value=response), \
             mock.patch.object(G, "_validate_fetch_target", return_value=target):
            result = G.fetch("https://example.com", retries=0)
        self.assertEqual(len(result["html"]), G.MAX_BYTES)
        response.close.assert_called_once()

    def test_fetch_closes_stream_when_iteration_fails(self):
        response = mock.Mock(
            status_code=200,
            headers={"Content-Type": "text/html"},
            url="https://example.com",
            encoding="utf-8",
        )
        response.iter_content.side_effect = OSError("stream failed")
        target = (G.urlparse("https://example.com"), ("93.184.216.34",))
        with mock.patch.object(G, "_request_pinned", return_value=response), \
             mock.patch.object(G, "_validate_fetch_target", return_value=target):
            result = G.fetch("https://example.com", retries=0)
        self.assertEqual(result["status"], 0)
        response.close.assert_called_once()

    def test_force_init_archives_stale_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            old_work = G.WORK
            G.WORK = Path(d)
            try:
                project = G.project_dir("demo")
                (project / "assets").mkdir(parents=True)
                (project / "geo.json").write_text("{}", "utf-8")
                (project / "assets" / "stale.txt").write_text("stale", "utf-8")
                args = types.SimpleNamespace(url="https://example.com", name="Example", slug="demo",
                                             market="global", max_pages=5, force=True)
                geo.cmd_init(args)
                self.assertFalse((project / "assets" / "stale.txt").exists())
                archives = list((Path(d) / ".archive").glob("demo-*"))
                self.assertEqual(len(archives), 1)
                self.assertTrue((archives[0] / "assets" / "stale.txt").is_file())
            finally:
                G.WORK = old_work

if __name__ == "__main__":
    unittest.main()
