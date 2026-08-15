import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import geolib as G
import publish as P


class PublishTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.original_work = G.WORK
        G.WORK = Path(self.tmp.name)
        self.addCleanup(setattr, G, "WORK", self.original_work)
        self.pdir = G.project_dir("demo")
        (self.pdir / "content").mkdir(parents=True)
        (self.pdir / "geo.json").write_text(json.dumps({
            "publishing": {"github": {"repo": "owner/repo", "branch": "main", "dir": "docs"}},
        }), "utf-8")
        (self.pdir / "content" / "article.md").write_text("# Safe title\n\nBody", "utf-8")

    def test_markdown_escapes_html_and_blocks_active_link_protocols(self):
        rendered = P.md2html('<img src=x onerror=alert(1)> [bad](javascript:alert(1)) '
                             '[good](https://example.com/?a=1&b=2)')
        self.assertIn("&lt;img", rendered)
        self.assertNotIn("javascript:", rendered)
        self.assertIn('href="https://example.com/?a=1&amp;b=2"', rendered)

    def test_source_path_cannot_escape_or_follow_external_symlink(self):
        outside = Path(self.tmp.name) / "secret.md"
        outside.write_text("secret", "utf-8")
        (self.pdir / "content" / "link.md").symlink_to(outside)
        for rel in ("../secret.md", "content/link.md", "content"):
            with self.assertRaises((OSError, ValueError)):
                P._read_source("demo", rel)

    def test_request_failure_is_sanitized_without_endpoint_or_credentials(self):
        with mock.patch.dict(os.environ, {"PUBLISH_WEBHOOK_URL": "https://secret.example/hook?token=TOKEN"}), \
             mock.patch.object(P.requests, "post", side_effect=requests.Timeout("TOKEN at endpoint")):
            result = P.publish("demo", "webhook", "content/article.md")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"],
                         "Publishing destination request failed; check URL, credentials, and network connectivity")
        self.assertNotIn("TOKEN", json.dumps(result))
        self.assertNotIn("secret.example", json.dumps(result))
        self.assertEqual(P.records("demo"), [])

    def test_github_rejects_invalid_repo_and_traversal_directory(self):
        self.assertFalse(P._pub_github({"repo": "owner/repo/extra"}, "x", "x", "x.md")["ok"])
        self.assertFalse(P._pub_github({"repo": "owner/repo", "dir": "../docs"}, "x", "x", "x.md")["ok"])

    def test_successful_publish_records_title_and_result(self):
        with mock.patch.dict(os.environ, {"PUBLISH_WEBHOOK_URL": "https://example.com/hook"}), \
             mock.patch.dict(P._IMPL, {"webhook": mock.Mock(return_value={"ok": True, "url": "https://example.com/post"})}):
            result = P.publish("demo", "webhook", "content/article.md")
        self.assertTrue(result["ok"])
        self.assertEqual(result["record"]["title"], "Safe title")
        self.assertEqual(len(P.records("demo")), 1)


if __name__ == "__main__":
    unittest.main()
