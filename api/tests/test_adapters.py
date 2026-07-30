import os

import pytest

from api.adapters.engine import geolib, with_tenant_context
from api.adapters.exceptions import GeoEngineError


def test_tenant_context_patches_paths_and_die_then_restores():
    original_root = geolib.ROOT
    original_work = geolib.WORK
    original_die = geolib.die

    with with_tenant_context("test-tenant", "example"):
        assert "test-tenant" in str(geolib.WORK)
        assert geolib.ROOT.name == "disvorai"
        with pytest.raises(GeoEngineError, match="test error"):
            geolib.die("test error")

    assert geolib.ROOT == original_root
    assert geolib.WORK == original_work
    assert geolib.die is original_die


def test_key_injection_supports_engine_codes_and_restores_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "old")
    os.environ.pop("DEEPSEEK_API_KEY", None)

    with with_tenant_context("tenant", "project", {"deepseek": "new", "OPENAI_API_KEY": "updated"}):
        assert os.environ["DEEPSEEK_API_KEY"] == "new"
        assert os.environ["OPENAI_API_KEY"] == "updated"

    assert "DEEPSEEK_API_KEY" not in os.environ
    assert os.environ["OPENAI_API_KEY"] == "old"


def test_context_rejects_path_traversal():
    with pytest.raises(ValueError):
        with with_tenant_context("../other-tenant", "project"):
            pass

