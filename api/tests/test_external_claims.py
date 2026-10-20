"""官网公开声明必须与能力清单、功能清单一致。"""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from api.adapters import capabilities  # noqa: E402


def _claims_module():
    spec = importlib.util.spec_from_file_location("check_claims", ROOT / "scripts" / "check_claims.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_pages_have_no_forbidden_claims():
    claims = _claims_module()
    catalog = capabilities.load_capabilities()
    problems = claims.check_plans()
    for page in claims.PUBLIC_PAGES:
        problems.extend(claims.check_page(
            page,
            len(capabilities.api_providers()),
            len(capabilities.manual_surfaces()),
            int(capabilities.load_features()["trial_days"]),
        ))
    assert problems == []
    assert catalog["version"]


def test_no_enterprise_plan_in_public_pages():
    for page in ("web/index.html", "web/pricing.html"):
        html = (ROOT / page).read_text("utf-8").lower()
        for phrase in ("enterprise sso", "oidc sso", "audit event logs", "dedicated private deploy",
                       "custom sla", "soc 2 certified"):
            assert phrase not in html, f"{page} still claims {phrase!r}"


def test_trial_copy_matches_feature_catalog():
    trial_days = capabilities.load_features()["trial_days"]
    assert trial_days == 14
    for language in ("en", "zh", "ja", "ko", "es", "fr", "de"):
        catalog = json.loads((ROOT / "api" / "i18n" / "messages" / f"{language}.json").read_text("utf-8"))
        assert "14" in catalog["landing.home.trial"], language
        assert "14" in catalog["landing.faq_4_q"], language
        assert "14" in catalog["landing.plan_starter_cta"], language


def test_engine_counts_are_explicit_in_public_pages():
    api_count = len(capabilities.api_providers())
    surface_count = len(capabilities.manual_surfaces())
    index = (ROOT / "web" / "index.html").read_text("utf-8")
    assert f'data-engine-count="{api_count}"' in index
    assert f'data-product-surface-count="{surface_count}"' in index
    assert "6 API engines" not in index
    assert "9 product surfaces" not in index
