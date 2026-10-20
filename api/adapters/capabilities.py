"""对外能力声明的唯一真源：引擎能力与功能清单都从仓库根文件读取。"""

import json
from functools import lru_cache
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CAPABILITIES_PATH = PROJECT_ROOT / "engine_capabilities.json"
FEATURES_PATH = PROJECT_ROOT / "features.yaml"


@lru_cache(maxsize=1)
def load_capabilities():
    return json.loads(CAPABILITIES_PATH.read_text("utf-8"))


@lru_cache(maxsize=1)
def load_features():
    return yaml.safe_load(FEATURES_PATH.read_text("utf-8")) or {}


def api_providers():
    return [item for item in load_capabilities()["api_providers"] if not item.get("product_surface")]


def manual_surfaces():
    return [item for item in load_capabilities()["manual_surfaces"] if item.get("product_surface")]


def all_surfaces():
    return api_providers() + manual_surfaces()


def engine_key_env():
    return {item["code"]: item["key_env"] for item in api_providers() if item.get("key_env")}


def default_sample_platforms():
    return load_capabilities()["default_platforms"]


def sampling_mode_label(mode):
    return load_capabilities()["sampling_modes"].get(mode, mode)


def features():
    return load_features().get("features") or []


def feature(feature_id):
    for item in features():
        if item.get("id") == feature_id:
            return item
    return None


def feature_enabled(feature_id, plan=None):
    item = feature(feature_id)
    if item is None or item.get("status") in ("planned", "removed", "internal"):
        return False
    if plan is None:
        return bool(item.get("public"))
    return plan in (item.get("entitlements") or ())


def public_plans():
    plans = load_features().get("plans") or {}
    return {
        name: definition
        for name, definition in plans.items()
        if definition.get("public", True)
    }


def public_features(plan=None):
    return [
        item for item in features()
        if item.get("public") and (plan is None or plan in (item.get("entitlements") or ()))
    ]


def catalog_fingerprint():
    payload = {
        "capabilities": load_capabilities(),
        "features": load_features(),
    }
    from api.projections.hashing import stable_sha256
    return stable_sha256(payload)
