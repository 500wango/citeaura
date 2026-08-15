import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import geo
import geolib as G


def args(url, **values):
    return types.SimpleNamespace(url=url, name="Acme", slug="demo", market="global",
                                 max_pages=values.get("max_pages", 5), force=False)


class GeoCliTest(unittest.TestCase):
    def test_init_rejects_non_http_and_missing_hosts(self):
        for url in ("ftp://example.com", "https:///missing", "http://[broken"):
            with self.subTest(url=url), self.assertRaises(SystemExit):
                geo.cmd_init(args(url))

    def test_init_rejects_non_positive_page_limit(self):
        with self.assertRaises(SystemExit):
            geo.cmd_init(args("example.com", max_pages=0))

    def test_init_normalizes_bare_domain_and_creates_directories(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(G, "WORK", Path(tmp)):
            result = geo.cmd_init(args("www.Example.com/"))
            self.assertEqual(result["brand"]["site"], "https://www.Example.com")
            self.assertEqual(result["slug"], "demo")
            for directory in ("evidence", "samples", "metrics", "reports", "history", "content"):
                self.assertTrue((Path(tmp) / "demo" / directory).is_dir())


if __name__ == "__main__":
    unittest.main()
