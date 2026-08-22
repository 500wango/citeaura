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
    return types.SimpleNamespace(url=url, name="Acme", slug="demo", market=values.get("market", "global"),
                                 max_pages=values.get("max_pages", 5), force=False)


class GeoCliTest(unittest.TestCase):
    def test_saas_pipeline_does_not_load_legacy_delivery_renderer(self):
        args = types.SimpleNamespace(no_delivery=True)
        with mock.patch.dict(sys.modules, {"deliver": None}):
            self.assertIsNone(geo._compile_standalone_delivery("demo", args))

    def test_standalone_pipeline_keeps_legacy_delivery_renderer(self):
        renderer = types.SimpleNamespace(run=mock.Mock())
        args = types.SimpleNamespace(no_delivery=False, legacy_delivery=True)
        with mock.patch.dict(sys.modules, {"deliver": renderer}):
            geo._compile_standalone_delivery("demo", args)
        renderer.run.assert_called_once_with("demo")

    def test_pipeline_does_not_write_legacy_delivery_by_default(self):
        args = types.SimpleNamespace(no_delivery=False, legacy_delivery=False)
        with mock.patch.dict(sys.modules, {"deliver": None}):
            self.assertIsNone(geo._compile_standalone_delivery("demo", args))

    def test_deliver_command_does_not_load_legacy_renderer_by_default(self):
        args = types.SimpleNamespace(legacy_delivery=False)
        with mock.patch.dict(sys.modules, {"deliver": None}):
            self.assertIsNone(geo.cmd_deliver(args))

    def test_init_rejects_non_http_and_missing_hosts(self):
        for url in ("ftp://example.com", "https:///missing", "http://[broken",
                    "https://user:pass@example.com"):
            with self.subTest(url=url), self.assertRaises(SystemExit):
                geo.cmd_init(args(url))

    def test_init_rejects_non_positive_page_limit(self):
        with self.assertRaises(SystemExit):
            geo.cmd_init(args("example.com", max_pages=0))

    def test_init_rejects_unknown_market(self):
        with self.assertRaises(SystemExit):
            geo.cmd_init(args("example.com", market="unknown"))

    def test_init_normalizes_bare_domain_and_creates_directories(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(G, "WORK", Path(tmp)):
            result = geo.cmd_init(args("www.Example.com/"))
            self.assertEqual(result["brand"]["site"], "https://www.Example.com")
            self.assertEqual(result["slug"], "demo")
            for directory in ("evidence", "samples", "metrics", "reports", "history", "content"):
                self.assertTrue((Path(tmp) / "demo" / directory).is_dir())


if __name__ == "__main__":
    unittest.main()
