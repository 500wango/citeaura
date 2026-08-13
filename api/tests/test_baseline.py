import json

from api.adapters import baseline
from api.adapters.log_translator import translate_engine_log


def test_manual_input_log_items_are_rendered_in_english():
    log = (
        "[geo]   Needs manual input: 成立时间, 工商主体, 可具名客户, "
        "支持的AI提供商范围, 套餐与定价详情\n"
    )

    translated = translate_engine_log(log)

    assert "成立时间" not in translated
    assert "Founding date and company history" in translated
    assert "Legal entity, registration jurisdiction, and company registration details" in translated
    assert "Named customers, customer count, and verified outcome case studies" in translated
    assert "Supported AI providers, models, and measurement coverage" in translated
    assert "Plan pricing, entitlements, and intended customer segments" in translated


def test_unknown_chinese_manual_input_is_replaced_with_safe_english():
    translated = translate_engine_log("[geo] Needs manual input: 尚未说明的独特事项\n")

    assert translated == "[geo] Needs manual input: Additional material brand information requiring manual verification\n"


def test_bootstrap_metadata_removes_domestic_questions(tmp_path, monkeypatch):
    project = tmp_path / "example"
    project.mkdir()
    config = {
        "slug": "example",
        "brand": {"name": "Example", "site": "https://example.com"},
        "questions": [{"id": "q001", "market": "cn", "text": "这个品牌怎么样？"}],
        "bootstrap": {
            "source": "Site Content + LLM Extraction",
            "uncertain": ["品牌成立时间未确认", "可具名客户、客户数量和实际效果案例未确认"],
        },
    }
    (project / "geo.json").write_text(json.dumps(config, ensure_ascii=False), "utf-8")
    monkeypatch.setattr(baseline.geolib, "WORK", tmp_path)

    result = baseline.normalize_bootstrap_metadata("example")

    assert result["bootstrap"]["uncertain"] == [
        "Founding date and company history",
        "Named customers, customer count, and verified outcome case studies",
    ]
    saved = json.loads((project / "geo.json").read_text("utf-8"))
    assert saved["questions"] == []
    assert saved["market"] == "global"
