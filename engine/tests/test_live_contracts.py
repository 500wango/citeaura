import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import crawl as C
import geolib as G
import sample as S


LIVE = os.environ.get("ENGINE_LIVE_TESTS") == "1"


@unittest.skipUnless(LIVE, "Set ENGINE_LIVE_TESTS=1 to run paid provider contracts")
class LiveProviderContracts(unittest.TestCase):
    def test_configured_provider_response_contracts(self):
        requested = {value.strip() for value in os.environ.get("ENGINE_LIVE_PROVIDERS", "").split(",") if value.strip()}
        providers = [code for code in S.PROVIDERS
                     if S.available(code) and (not requested or code in requested)]
        if not providers:
            self.skipTest("No requested provider API keys are configured")
        timeout = int(os.environ.get("ENGINE_LIVE_TIMEOUT", "45"))
        for code in providers:
            with self.subTest(provider=code):
                result = S.ask(code, "Reply with the single word OK.", timeout=timeout)
                self.assertTrue(result.get("ok"), result.get("error", "provider call failed"))
                self.assertTrue(str(result.get("answer") or "").strip())
                self.assertIsInstance(result.get("citations", []), list)
                self.assertIsInstance(result.get("searched"), bool)


@unittest.skipUnless(LIVE, "Set ENGINE_LIVE_TESTS=1 to run the live crawl contract")
class LiveCrawlContract(unittest.TestCase):
    def test_configured_public_site_contract(self):
        url = os.environ.get("ENGINE_LIVE_CRAWL_URL", "").strip()
        if not url:
            self.skipTest("ENGINE_LIVE_CRAWL_URL is not configured")
        with tempfile.TemporaryDirectory() as tmp:
            original_work = G.WORK
            G.WORK = Path(tmp)
            try:
                pdir = G.project_dir("live")
                pdir.mkdir()
                (pdir / "geo.json").write_text(json.dumps({
                    "brand": {"name": "Live contract", "site": url},
                    "market": "global", "pages": {"seed": [], "max": 3},
                }), "utf-8")
                result = C.run("live", max_pages=3, delay=0)
            finally:
                G.WORK = original_work
        self.assertGreaterEqual(result["pages_ok"], 1)
        self.assertLessEqual(result["pages_crawled"], 3)


if __name__ == "__main__":
    unittest.main()
