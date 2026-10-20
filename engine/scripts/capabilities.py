"""引擎侧能力清单加载与注册表一致性校验。"""

import json
from pathlib import Path

CAPABILITIES_PATH = Path(__file__).resolve().parents[2] / "engine_capabilities.json"


def load():
    return json.loads(CAPABILITIES_PATH.read_text("utf-8"))


def provider_codes():
    return {item["code"] for item in load()["api_providers"]}


def manual_codes():
    return {item["code"] for item in load()["manual_surfaces"]}


def default_platforms():
    return load()["default_platforms"]


def validate_registries(providers, default_platforms_map):
    """返回能力清单与引擎注册表的差异；空列表表示一致。"""
    problems = []
    catalog = load()
    declared = {item["code"] for item in catalog["api_providers"]}
    manual = {item["code"] for item in catalog["manual_surfaces"]}
    actual = set(providers)
    if declared != actual:
        problems.append(f"api providers mismatch: catalog={sorted(declared)} engine={sorted(actual)}")
    if declared & manual:
        problems.append(f"codes declared as both api and manual: {sorted(declared & manual)}")
    for market, platforms in catalog["default_platforms"].items():
        if list(default_platforms_map.get(market) or []) != list(platforms):
            problems.append(f"default platforms mismatch for {market}")
    unknown = set(default_platforms_map.get("both") or ()) - declared - manual
    if unknown:
        problems.append(f"default platforms not declared: {sorted(unknown)}")
    return problems
