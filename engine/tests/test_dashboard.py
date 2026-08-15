import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import dashboard as D
import geolib as G


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


if __name__ == "__main__":
    unittest.main()
