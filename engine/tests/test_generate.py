import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import generate as GEN
import geolib as G


class GenerateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.original_work = G.WORK
        G.WORK = Path(self.tmp.name)
        self.addCleanup(setattr, G, "WORK", self.original_work)
        self.pdir = G.project_dir("demo")
        (self.pdir / "content").mkdir(parents=True)
        self.cfg = {
            "brand": {
                "name": "Acme", "name_en": "Acme", "site": "https://acme.example",
                "definition_en": "Acme is proposal workflow software.",
                "aliases": ["Acme Flow"], "industry": "Proposal software",
                "target_users": "Sales teams", "application_category": "BusinessApplication",
                "offers": [{"name": "Pro", "price": "20", "currency": "USD"},
                           {"name": "Unknown", "price": "TBD", "currency": "USD"}],
            },
            "market": "global",
            "competitors": [{"name": "KnownCo", "market": "global", "confirmed": True},
                            {"name": "CandidateCo", "market": "global", "confirmed": False}],
            "questions": [{"id": "q001", "market": "global", "group": "comparison",
                           "text": "What are the best proposal tools?",
                           "answer_en": "Compare workflow fit, integrations, and support."}],
        }
        (self.pdir / "geo.json").write_text(json.dumps(self.cfg), "utf-8")
        G.write_json(self.pdir / "audit.json", {"pages": [
            {"url": "https://acme.example/features", "title": "Features", "score": 90},
        ]})
        (self.pdir / "content" / "facts.md").write_text(
            "## Canonical Definition\n\n> Acme is verified proposal software.\n\n"
            "## Key Numbers\n\n| Fact | Value | Source | Evidence |\n|---|---|---|---|\n"
            "| Users | 500 | Annual report | page 2 |\n"
            "| Pending | TBD | Unknown | |\n\n"
            "**Good fit**:\n\n- Sales teams\n\n**Not a fit**:\n\n- Personal notes\n",
            "utf-8",
        )

    def test_parse_facts_filters_placeholders(self):
        facts = GEN.parse_facts("demo")
        self.assertEqual(facts["definition"], "Acme is verified proposal software.")
        self.assertEqual(facts["numbers"], [
            {"fact": "Users", "value": "500", "source": "Annual report", "evidence": "page 2"},
        ])
        self.assertEqual(facts["suitable"], ["Sales teams"])
        self.assertEqual(facts["unsuitable"], ["Personal notes"])

    def test_jsonld_omits_placeholder_offers_and_includes_verified_faq(self):
        schemas = GEN.gen_jsonld("demo")
        self.assertEqual(schemas["software-application"]["offers"], [
            {"@type": "Offer", "name": "Pro", "price": "20", "priceCurrency": "USD"},
        ])
        self.assertEqual(len(schemas["faq-page"]["mainEntity"]), 1)

    def test_selective_generation_and_manifest(self):
        result = GEN.run("demo", which=["jsonld"])
        self.assertTrue((self.pdir / "assets" / "jsonld" / "organization.json").is_file())
        self.assertFalse((self.pdir / "assets" / "llms.en.txt").exists())
        self.assertTrue(all(path.startswith("assets/jsonld/") for path in result["generated_assets"]))

    def test_invalid_generation_options_fail_explicitly(self):
        with self.assertRaisesRegex(ValueError, "Unknown asset"):
            GEN.run("demo", which=["unknown"])
        with self.assertRaisesRegex(ValueError, "non-negative"):
            GEN.run("demo", which=["outlines"], with_draft=True, draft_limit=-1)

    def test_draft_failure_returns_empty_and_excludes_unconfirmed_competitor(self):
        outline = GEN.gen_outlines("demo")[0]
        captured = {}

        def ask(_platform, prompt, timeout, **_kwargs):
            captured["prompt"] = prompt
            return {"ok": False, "error": "timeout"}

        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test"}), \
             mock.patch("sample.ask", side_effect=ask):
            self.assertEqual(GEN.draft("demo", outline, provider="deepseek"), "")
        self.assertIn("KnownCo", captured["prompt"])
        self.assertNotIn("CandidateCo", captured["prompt"])

    def test_asset_lint_rejects_placeholders_and_untranslated_english(self):
        self.assertEqual(set(GEN._asset_issues("TODO 中文", "en")),
                         {"contains_placeholder", "contains_untranslated_text"})

    def test_llms_txt_places_unscored_pages_after_measured_pages(self):
        G.write_json(self.pdir / "audit.json", {"pages": [
            {"url": "https://acme.example/contact", "title": "Contact", "score": None},
            {"url": "https://acme.example/features", "title": "Features", "score": 90},
        ]})
        text = GEN.gen_llms_txt("demo", "en")
        self.assertLess(text.index("https://acme.example/features"),
                        text.index("https://acme.example/contact"))


if __name__ == "__main__":
    unittest.main()
