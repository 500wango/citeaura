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
        self.assertFalse(P._pub_github({"repo": "owner/repo", "dir": r"docs\..\x"}, "x", "x", "x.md")["ok"])

    def test_destination_urls_reject_credentials_and_active_protocols(self):
        self.assertEqual(P._http_url("javascript:alert(1)"), "")
        self.assertEqual(P._http_url("https://user:pass@example.com"), "")
        self.assertEqual(P._http_url("https://example.com/path"), "https://example.com/path")

    def test_returned_active_url_is_removed_before_recording(self):
        with mock.patch.dict(os.environ, {"PUBLISH_WEBHOOK_URL": "https://example.com/hook"}), \
             mock.patch.dict(P._IMPL, {"webhook": mock.Mock(return_value={
                 "ok": True, "url": "javascript:alert(1)",
             })}):
            result = P.publish("demo", "webhook", "content/article.md")
        self.assertEqual(result["url"], "")
        self.assertEqual(result["record"]["url"], "")

    def test_successful_publish_records_title_and_result(self):
        with mock.patch.dict(os.environ, {"PUBLISH_WEBHOOK_URL": "https://example.com/hook"}), \
             mock.patch.dict(P._IMPL, {"webhook": mock.Mock(return_value={"ok": True, "url": "https://example.com/post"})}):
            result = P.publish("demo", "webhook", "content/article.md")
        self.assertTrue(result["ok"])
        self.assertEqual(result["record"]["title"], "Safe title")
        self.assertEqual(len(P.records("demo")), 1)


class WechatErrorTest(unittest.TestCase):
    """微信通道的异常文本可能带整条 URL/密钥，返回值只能是稳定错误码。"""

    ENV = {"WECHAT_APPID": "wx-app", "WECHAT_APPSECRET": "TOP-SECRET"}
    SECRET_MARKERS = ("TOP-SECRET", "api.weixin.qq.com", "access_token")

    def _assert_sanitized(self, result):
        payload = json.dumps(result)
        for marker in self.SECRET_MARKERS:
            self.assertNotIn(marker, payload)

    def test_token_request_failure_returns_stable_error_code(self):
        with mock.patch.dict(os.environ, self.ENV), \
             mock.patch.object(P.requests, "get", side_effect=requests.ConnectionError(
                 "TOP-SECRET at https://api.weixin.qq.com/cgi-bin/token?secret=TOP-SECRET")):
            result = P._pub_wechat({"thumb_media_id": "m"}, "# T\n\nBody", "T", "a.md")
        self.assertEqual(result, {"ok": False, "error": "wechat_token_request_failed"})
        self._assert_sanitized(result)

    def test_token_api_error_returns_errcode_only(self):
        token = mock.Mock()
        token.json.return_value = {"errcode": 40001,
                                   "errmsg": "invalid credential TOP-SECRET"}
        with mock.patch.dict(os.environ, self.ENV), \
             mock.patch.object(P.requests, "get", return_value=token):
            result = P._pub_wechat({"thumb_media_id": "m"}, "# T\n\nBody", "T", "a.md")
        self.assertEqual(result, {"ok": False, "error": "wechat_token_unavailable:errcode=40001"})
        self._assert_sanitized(result)

    def test_draft_request_failure_returns_stable_error_code(self):
        token = mock.Mock()
        token.json.return_value = {"access_token": "tok-123"}
        with mock.patch.dict(os.environ, self.ENV), \
             mock.patch.object(P.requests, "get", return_value=token), \
             mock.patch.object(P.requests, "post", side_effect=requests.Timeout("tok-123")):
            result = P._pub_wechat({"thumb_media_id": "m"}, "# T\n\nBody", "T", "a.md")
        self.assertEqual(result, {"ok": False, "error": "wechat_draft_request_failed"})
        self._assert_sanitized(result)

    def test_draft_api_error_returns_errcode_only(self):
        token = mock.Mock()
        token.json.return_value = {"access_token": "tok-123"}
        draft = mock.Mock()
        draft.json.return_value = {"errcode": 45009, "errmsg": "api freq out of limit"}
        with mock.patch.dict(os.environ, self.ENV), \
             mock.patch.object(P.requests, "get", return_value=token), \
             mock.patch.object(P.requests, "post", return_value=draft):
            result = P._pub_wechat({"thumb_media_id": "m"}, "# T\n\nBody", "T", "a.md")
        self.assertEqual(result, {"ok": False, "error": "wechat_draft_unavailable:errcode=45009"})
        self._assert_sanitized(result)


if __name__ == "__main__":
    unittest.main()
