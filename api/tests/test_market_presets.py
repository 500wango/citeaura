"""市场预设、语言解析与请求默认值测试。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine" / "scripts"))

import languages  # noqa: E402

from api.adapters import market_presets, preflight  # noqa: E402
from api.projects.schemas import ProjectCreate, SampleEstimateRequest, SampleRequest  # noqa: E402


def test_market_presets_resolve_language():
    assert market_presets.preset("cn") == {
        "market": "cn", "question_language": "zh", "report_language": "en",
    }
    assert market_presets.preset("global")["question_language"] == "en"
    assert market_presets.preset("both")["question_language"] == "auto"
    assert market_presets.normalize_market("unknown", "both") == "both"
    assert market_presets.normalize_question_language("de") == "de"
    assert market_presets.normalize_question_language("xx") == "auto"


def test_engine_language_resolution():
    assert languages.resolve_question_language("cn") == "zh"
    assert languages.resolve_question_language("global") == "en"
    assert languages.resolve_question_language("both") == "auto"
    assert languages.resolve_question_language("cn", "ja") == "ja"
    assert languages.question_language({"market": "cn"}, "both") == "zh"
    assert languages.question_language({"market": "global"}, "both") == "en"
    assert languages.instruction("xx") == "English"


def test_schema_defaults_match_engine():
    from api.analytics.clustered_stats import DEFAULT_REPEAT

    project = ProjectCreate(url="https://example.com")
    assert project.market is None
    assert project.question_language == "auto"
    assert project.report_language == "en"
    assert SampleRequest().repeat == DEFAULT_REPEAT
    assert SampleEstimateRequest().repeat == DEFAULT_REPEAT


def test_preflight_suggests_market_from_tld():
    assert preflight.suggest_market("https://brand.cn") == "cn"
    assert preflight.suggest_market("https://brand.com.cn") == "cn"
    assert preflight.suggest_market("https://brand.example") == "global"
