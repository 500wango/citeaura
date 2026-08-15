import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import verify as V


def task(check, **values):
    return {"acceptance": {"type": "auto", "check": check}, "affected": [], **values}


class VerifyTest(unittest.TestCase):
    def test_manual_and_unknown_checks_are_indeterminate(self):
        self.assertIsNone(V.check({"acceptance": {"type": "manual"}}, {}, {})[0])
        ok, note, progress = V.check(task("not.registered"), {}, {})
        self.assertIsNone(ok)
        self.assertIn("Unknown checker", note)
        self.assertIsNone(progress)

    def test_brand_domain_check_normalizes_targets_and_evidence(self):
        metrics = {"platforms": {
            "p": {"market": "global", "top_brand_cited_domains": {
                "HTTPS://News.Example.COM.:443/article": 2,
                "bad.example": -5,
            }},
        }}
        ok, _note, progress = V.check(task("external.brand_any:www.example.com"), {}, metrics)
        self.assertTrue(ok)
        self.assertEqual(progress["cur"], 1)

    def test_observed_domain_without_brand_evidence_does_not_pass(self):
        metrics = {"platforms": {"p": {
            "top_cited_domains": {"example.com": 3}, "top_brand_cited_domains": {},
        }}}
        self.assertFalse(V.check(task("external.brand_any:example.com"), {}, metrics)[0])

    def test_relative_checks_use_full_baseline_and_cohort(self):
        urls = [f"https://example.com/{i}" for i in range(10)]
        audit = {"pages": [{"url": url, "blocks": {"faq": i >= 5}, "word_count": 500}
                           for i, url in enumerate(urls)]}
        ok, _note, progress = V.check(task("pages.block:faq", affected=urls[:2],
                                           verification_cohort=urls, baseline_count=10), audit, {})
        self.assertTrue(ok)
        self.assertEqual(progress["base"], 10)
        self.assertEqual(progress["cur"], 5)

    def test_malformed_pages_are_ignored_instead_of_crashing(self):
        ok, note, _ = V.check(task("pages.static_text", verification_cohort=["https://x"]),
                              {"pages": [None, {}, {"url": "https://x", "word_count": 200}]}, {})
        self.assertTrue(ok, note)


if __name__ == "__main__":
    unittest.main()
