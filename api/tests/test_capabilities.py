"""对外能力清单与引擎注册表一致性测试。"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "scripts"))

from api.adapters import capabilities  # noqa: E402


def test_catalog_counts_and_shape():
    catalog = capabilities.load_capabilities()
    assert len(capabilities.api_providers()) == 10
    assert len(capabilities.manual_surfaces()) == 12
    assert catalog["version"]
    for item in capabilities.all_surfaces():
        assert item["sampling_mode"] in catalog["sampling_modes"]
        assert item["market"] in ("cn", "global")
        assert isinstance(item["search"], bool)
        assert item["canary"]["status"]


def test_catalog_matches_engine_registries():
    import geo
    import sample

    from capabilities import validate_registries

    assert {item["code"] for item in capabilities.api_providers()} == set(sample.PROVIDERS)
    assert {item["code"] for item in capabilities.manual_surfaces()} == set(sample.MANUAL_ONLY)
    assert capabilities.engine_key_env() == {
        code: provider["key_env"] for code, provider in sample.PROVIDERS.items()
    }
    assert capabilities.default_sample_platforms() == geo.DEFAULT_PLATFORMS
    assert validate_registries(sample.PROVIDERS, geo.DEFAULT_PLATFORMS) == []


def test_custom_providers_are_not_builtin():
    codes = {item["code"] for item in capabilities.all_surfaces()}
    assert not {code for code in codes if code.startswith("custom_")}


def test_features_state_is_honest():
    features = capabilities.features()
    assert features
    ids = [item["id"] for item in features]
    assert len(ids) == len(set(ids))
    for item in features:
        assert item["status"] in ("live", "beta", "planned", "internal", "removed")
        if item["status"] in ("planned", "removed", "internal"):
            assert item["public"] is False
    assert capabilities.feature("enterprise_sso")["status"] == "removed"
    assert capabilities.feature_enabled("enterprise_sso") is False
    assert capabilities.feature_enabled("scheduled_monitoring", "agency") is True
    assert capabilities.feature_enabled("white_label_delivery", "pro") is False


def test_public_plans_exclude_enterprise():
    plans = capabilities.public_plans()
    assert set(plans) == {"trial", "starter", "pro", "agency"}
    assert plans["trial"]["projects"] == 3
    assert plans["starter"]["projects"] == 3
    assert plans["pro"]["projects"] == 10
    assert plans["agency"]["projects"] == 30
    assert capabilities.load_features()["trial_days"] == 14


def test_catalog_fingerprint_is_stable():
    first = capabilities.catalog_fingerprint()
    capabilities.load_capabilities.cache_clear()
    capabilities.load_features.cache_clear()
    assert capabilities.catalog_fingerprint() == first
