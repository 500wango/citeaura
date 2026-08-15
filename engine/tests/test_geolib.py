import json, tempfile, types, unittest
from pathlib import Path
import sys; sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
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
