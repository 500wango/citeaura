import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import expand as E
import geolib as G


class ExpandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.original_work = G.WORK
        G.WORK = Path(self.tmp.name)
        self.addCleanup(setattr, G, "WORK", self.original_work)
        self.pdir = G.project_dir("demo")
        self.pdir.mkdir(parents=True)

    def _write_config(self, **overrides):
        cfg = {
            "brand": {"name": "Acme", "aliases": ["ACME"], "industry": "Proposal software",
                      "products": ["Acme Flow"]},
            "market": "global",
            "competitors": [
                {"name": "Confirmed", "market": "global", "confirmed": True},
                {"name": "Candidate", "market": "global", "confirmed": False},
            ],
            "questions": [{"id": "q001", "text": "What are Acme alternatives?"}],
        }
        cfg.update(overrides)
        (self.pdir / "geo.json").write_text(json.dumps(cfg), "utf-8")
        return cfg

    def test_roots_dedupe_aliases_and_skip_unconfirmed_competitors(self):
        roots = E._roots(self._write_config())
        values = [row["root"] for row in roots]
        self.assertEqual(values.count("Acme"), 1)
        self.assertIn("Confirmed", values)
        self.assertNotIn("Candidate", values)

    def test_llm_length_mismatch_preserves_templates(self):
        terms = [{"term": "Acme review", "question": "template one"},
                 {"term": "Acme pricing", "question": "template two"}]
        answer = {"ok": True, "answer": '{"questions": ["only one"]}'}
        with mock.patch("sample.pick_llm", return_value="deepseek"), \
             mock.patch("sample.ask", return_value=answer):
            self.assertFalse(E._convert_llm(terms))
        self.assertEqual([row["question"] for row in terms], ["template one", "template two"])

    def test_run_deduplicates_and_preserves_first_seen_case_insensitively(self):
        self._write_config(competitors=[], questions=[])
        G.write_json(self.pdir / "expand.json", {
            "generated_at": "2026-08-01",
            "terms": [{"term": "Acme Review", "first_seen": "2026-07-01"}],
        })

        def suggestions(query, **_kwargs):
            return ["acme review", "ACME REVIEW", "Acme login", "Unrelated product"]

        with mock.patch.object(E, "suggest_google", side_effect=suggestions), \
             mock.patch.object(E.time, "sleep"):
            result = E.run("demo", use_llm=False)
        review = next(row for row in result["terms"] if row["term"].casefold() == "acme review")
        self.assertEqual(review["first_seen"], "2026-07-01")
        self.assertFalse(review["new"])
        self.assertEqual(sum(row["term"].casefold() == "acme review" for row in result["terms"]), 1)
        self.assertFalse(any("login" in row["term"].lower() for row in result["terms"]))


if __name__ == "__main__":
    unittest.main()
