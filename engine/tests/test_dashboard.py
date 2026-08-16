import json
import io
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import dashboard as D
import geolib as G
import jobs as J


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.original_work = G.WORK
        G.WORK = Path(self.tmp.name) / "work"
        self.addCleanup(setattr, G, "WORK", self.original_work)
        self.pdir = G.project_dir("demo")
        (self.pdir / "assets" / "nested").mkdir(parents=True)
        (self.pdir / "geo.json").write_text(json.dumps({
            "brand": {"name": "Acme", "site": "https://acme.example"}, "market": "global",
        }), "utf-8")
        (self.pdir / "assets" / "nested" / "asset.md").write_text("hello", "utf-8")

    def test_asset_tree_and_reader_are_confined(self):
        self.assertEqual(D.asset_tree("demo")[0]["path"], "nested/asset.md")
        self.assertEqual(D.read_asset("demo", "nested/asset.md")["text"], "hello")
        with self.assertRaises(PermissionError):
            D.read_asset("demo", "../../geo.json")

    def test_asset_tree_ignores_symlinks(self):
        outside = Path(self.tmp.name) / "outside.md"
        outside.write_text("secret", "utf-8")
        (self.pdir / "assets" / "linked.md").symlink_to(outside)
        self.assertNotIn("linked.md", [row["path"] for row in D.asset_tree("demo")])

    def test_project_list_tolerates_missing_optional_outputs(self):
        projects = D.list_projects()
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["name"], "Acme")
        self.assertIsNone(projects[0]["avg_score"])

    def test_write_env_replaces_values_and_uses_private_permissions(self):
        root = Path(self.tmp.name) / "engine"
        root.mkdir()
        (root / ".env").write_text("KEEP=1\nTOKEN=old\nexport TOKEN=older\n", "utf-8")
        with mock.patch.object(G, "ROOT", root), mock.patch.dict(os.environ, {}, clear=False):
            D.write_env({"TOKEN": "new", "EMPTY": ""})
            text = (root / ".env").read_text("utf-8")
            self.assertEqual(text.count("TOKEN="), 1)
            self.assertIn("TOKEN=new", text)
            self.assertEqual(os.stat(root / ".env").st_mode & 0o777, 0o600)

    def test_dashboard_request_origin_is_confined_to_loopback(self):
        self.assertTrue(D.trusted_request("127.0.0.1:8765", "http://127.0.0.1:8765"))
        self.assertTrue(D.trusted_request("localhost:8765", ""))
        self.assertFalse(D.trusted_request("attacker.example:8765", "http://attacker.example:8765"))
        self.assertFalse(D.trusted_request("127.0.0.1:8765", "https://attacker.example"))
        self.assertFalse(D.trusted_request("127.0.0.1:8765", "", "cross-site"))

    def test_sample_import_path_rejects_traversal_and_non_markdown(self):
        self.assertEqual(D.sample_import_path("demo", "2026-08-15-manual.md").parent,
                         self.pdir / "samples")
        for filename in ("../manual.md", "nested/manual.md", ".hidden.md", "manual.jsonl"):
            with self.assertRaises(ValueError):
                D.sample_import_path("demo", filename)

    def test_request_body_is_bounded_and_requires_an_object(self):
        handler = object.__new__(D.Handler)
        handler.headers = {"Content-Length": "2"}
        handler.rfile = io.BytesIO(b"[]")
        with self.assertRaisesRegex(ValueError, "request_body_must_be_object"):
            handler._body()

        handler.headers = {"Content-Length": str(D.MAX_BODY_BYTES + 1)}
        handler.rfile = io.BytesIO()
        with self.assertRaisesRegex(ValueError, "request_body_must_not_exceed"):
            handler._body()

    def test_monitor_validates_interval_and_preserves_latest_config(self):
        config_path = self.pdir / "geo.json"
        config = G.read_json(config_path)
        config["monitor"] = {"every_days": 0, "next_run": ""}
        G.write_json(config_path, config)
        with mock.patch.object(J, "start") as start:
            D._monitor_tick()
        start.assert_not_called()

        config["monitor"] = {"every_days": 2, "next_run": ""}
        G.write_json(config_path, config)

        def update_during_start(*_args):
            latest = G.read_json(config_path)
            latest["brand"]["name"] = "Updated concurrently"
            G.write_json(config_path, latest)

        with mock.patch.object(J, "running_for", return_value=None), \
             mock.patch.object(J, "start", side_effect=update_during_start):
            D._monitor_tick()
        latest = G.read_json(config_path)
        self.assertEqual(latest["brand"]["name"], "Updated concurrently")
        self.assertTrue(latest["monitor"]["next_run"])

    def test_monitor_loop_honors_shutdown_event(self):
        stop = threading.Event()
        stop.set()
        D._monitor_loop(stop, interval=60)


if __name__ == "__main__":
    unittest.main()
