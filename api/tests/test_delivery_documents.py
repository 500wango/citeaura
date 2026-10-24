import pytest
from api.adapters.delivery_documents import _audit_markdown
from api.adapters.engine import geolib
from api.adapters.pdf import _cjk_font, render_markdown_pdf


def test_pdf_selects_a_builtin_cjk_font_per_script():
    assert _cjk_font("中文报告") == "STSong-Light"
    assert _cjk_font("日本語レポート") == "HeiseiMin-W3"
    assert _cjk_font("한국어 보고서") == "HYSMyeongJo-Medium"
    assert _cjk_font("English report") is None


def test_pdf_renders_chinese_markdown_with_the_cjk_font():
    data = render_markdown_pdf("# 中文报告\n\n## 发现\n\n- 品牌事实已确认\n", title="中文报告")
    assert data.startswith(b"%PDF-")
    assert b"STSong-Light" in data

def test_delivery_table_uses_not_recorded_for_missing_platform_modes(monkeypatch):
    monkeypatch.setattr(geolib, "read_json", lambda p, d=None: {})
    monkeypatch.setattr(geolib, "read_jsonl", lambda p: [])
    
    from api.adapters import measurement
    monkeypatch.setattr(measurement, "sampling_quality", lambda slug: {})
    
    metrics = {
        "platforms": {
            "openai": {
                "name": "OpenAI",
                "samples": 0,
                "mention_rate": None,
                "top3_rate": None,
                "own_domain_cite_rate": None
            }
        }
    }
    
    markdown = _audit_markdown("demo", geolib.Path("/tmp"), "Demo", "example.com", {}, metrics)
    assert "Not recorded" in markdown
    assert "API - Parametric knowledge" not in markdown


def test_audience_checklists_split_tickets_by_execution_role():
    from api.adapters.delivery_documents import audience_checklists

    tickets = [
        {"id": "T1", "package": "Page technology", "title_en": "Fix rendering", "status": "done"},
        {"id": "T2", "package": "Content matrix", "title_en": "Add comparison page", "status": "todo"},
        {"id": "T3", "package": "External evidence", "title_en": "Publish roundup", "status": "todo"},
    ]
    checklists = audience_checklists(tickets)
    assert set(checklists) == {
        "developers-checklist.md", "content-checklist.md", "outreach-checklist.md",
    }
    assert "- [x] T1 · Fix rendering" in checklists["developers-checklist.md"]
    assert "- [ ] T2 · Add comparison page" in checklists["content-checklist.md"]
    assert "- [ ] T3 · Publish roundup" in checklists["outreach-checklist.md"]
    assert "not randomized" in checklists["developers-checklist.md"]
