import json
from pathlib import Path

import pytest

from api.adapters import delivery
from api.adapters.exceptions import GeoEngineError


def seed_delivery_project(tmp_path: Path, *, legacy=True):
    project = tmp_path / "example"
    output = project / "delivery" / "2026-07-31"
    output.mkdir(parents=True)
    if legacy:
        (output / "01-诊断报告.md").write_text("# 中文旧报告\n", "utf-8")
        (output / "index.html").write_text("<p>&#20013;&#25991;</p>", "utf-8")

    _write_json(project / "geo.json", {
        "brand": {"name": "Example", "site": "https://example.com"},
        "market": "both",
        "questions": [{"id": "q001", "text": "What is Example?", "market": "global"}],
    })
    _write_json(project / "audit.json", {
        "audited_at": "2026-07-31T12:00:00+00:00",
        "market": "both",
        "site": {
            "root": "https://example.com", "has_sitemap": False, "has_llms_txt": False,
            "ai_bots_blocked": [], "pages_ok": 1, "pages_crawled": 1,
        },
        "language_coverage": {"zh_pages": 0, "en_pages": 1},
        "page_count": 1,
        "avg_score": 42.5,
        "grade_distribution": {"A": 0, "B": 0, "C": 1, "D": 0},
        "block_gap": [{"block": "定义", "missing_pages": 1, "total": 1}],
        "pages": [{
            "url": "https://example.com", "title": "Example", "word_count": 300,
            "score": 42.5, "grade": "C", "issue_codes": ["NO_DEFINITION", "NO_JSONLD"],
        }],
    })
    _write_json(project / "tasks.json", {
        "generated_at": "2026-07-31T12:00:00+00:00",
        "baseline": {"avg_score": 42.5, "pages": 1},
        "tasks": [
            {
                "id": "T-001", "priority": "P0", "package": "页面技术", "market": "both",
                "title": "补 sitemap.xml 并提交各搜索引擎",
                "why": "无 sitemap，收录效率和覆盖面打折（method.md 可抓取性）",
                "action": "生成 sitemap.xml，robots.txt 里声明，提交百度/必应/Google/夸克",
                "owner": "开发", "effort": "S", "window": "30天", "affected": [],
                "acceptance": {"type": "auto", "check": "site.has_sitemap", "desc": "重抓能取到 sitemap.xml"},
                "status": "todo",
            },
            {
                "id": "T-002", "priority": "P1", "package": "内容矩阵", "market": "both",
                "title": "全站补「定义」抽取块", "why": "1/1 页缺失；实测影响力增益 +57.3%（method.md 可抽取块）",
                "action": "参照 content-patterns.md，在核心页补定义块；定义句需与事实卡逐字一致",
                "owner": "内容", "effort": "M", "window": "60天", "affected": ["https://example.com"],
                "acceptance": {"type": "auto", "check": "pages.block:定义", "desc": "缺「定义」的页面数下降 ≥ 50%"},
                "status": "doing",
            },
        ],
    })
    _write_json(project / "verify" / "2026-07-31-120000.json", {
        "verified_at": "2026-07-31T12:00:00+00:00",
        "audit_avg_score": 42.5,
        "changed": 0,
        "results": [
            {
                "id": "T-001", "priority": "P0", "verdict": "未达标", "note": "sitemap 仍缺失",
                "progress": None,
            },
            {
                "id": "T-002", "priority": "P1", "verdict": "待人工", "note": "需人工确认",
                "progress": {"label": "缺定义块的页面", "cur": 1, "target": 0, "op": "lte"},
            },
        ],
    })
    _write_json(project / "blueprint.json", {
        "coverage": {
            "channel_total": 2, "channel_covered": 0, "p0p1_total": 2, "p0p1_covered": 0,
            "content_total": 1, "content_done": 0,
        },
        "channels": [
            {"id": "official_en", "name": "英文官网", "priority": "P0", "market": "global", "covered": False},
            {"id": "wikipedia", "name": "Wikipedia", "priority": "P1", "market": "global", "covered": False},
        ],
        "contents": [{
            "id": "q001", "market": "global", "group": "品牌验证", "question": "What is Example?",
            "form": "About Us & Knowledge Graph", "status": "gap",
        }],
    })
    _write_json(project / "metrics" / "2026-07-31.json", {
        "date": "2026-07-31",
        "platforms": {
            "openai": {
                "label": "OpenAI", "market": "global", "samples": 2,
                "mention_rate": 0.5, "top3_rate": 0.5, "own_domain_cite_rate": 0,
            },
        },
    })
    (project / "samples").mkdir()
    (project / "samples" / "2026-07-31.jsonl").write_text(
        json.dumps({
            "platform": "openai", "market": "global", "sample_mode": "api", "terminal": "api", "search_enabled": False,
        }) + "\n",
        "utf-8",
    )
    (project / "assets").mkdir()
    (project / "assets" / "llms.en.txt").write_text(
        "# Example\n\n> （待补：一句话定义，必须与官网首屏和 JSON-LD description 逐字一致）\n",
        "utf-8",
    )
    _write_json(project / "assets" / "jsonld" / "organization.json", {
        "@context": "https://schema.org", "@type": "Organization", "name": "Example",
        "sameAs": ["<填：百科页>"],
    })
    (project / "assets" / "snippets").mkdir()
    (project / "assets" / "snippets" / "definition.en.html").write_text("<!-- 中文模板 -->", "utf-8")
    (project / "assets" / "snippets" / "faq.en.html").write_text("<!-- 中文模板 -->", "utf-8")
    (project / "assets" / "outlines").mkdir()
    (project / "assets" / "outlines" / "q001.md").write_text("# 中文大纲\n", "utf-8")
    _write_json(project / "assets" / "index.json", {"assets": ["assets/outlines/（1 份）"]})
    return project, output


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")


def _patch_project(monkeypatch, project):
    monkeypatch.setattr(delivery.geolib, "project_dir", lambda slug: project)
    monkeypatch.setattr(delivery.geolib, "today", lambda: "2026-07-31")
    monkeypatch.setattr(delivery.geolib, "now_iso", lambda: "2026-07-31T12:00:00+00:00")


def test_delivery_contract_rebuilds_legacy_package_in_english(tmp_path, monkeypatch):
    project, output = seed_delivery_project(tmp_path)
    _patch_project(monkeypatch, project)

    result = delivery.ensure_delivery_contract("example", output)

    assert result == output
    expected = {
        *(f"{number}-{name}.md" for number, name in delivery.REQUIRED_DOCUMENTS.items()),
        *(f"{number}-{name}.html" for number, name in delivery.REQUIRED_DOCUMENTS.items()),
        "03-Ticket-Log.csv", "README.md", "index.md", "index.html", "assets/index.json",
    }
    files = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()}
    assert expected <= files
    assert "01-诊断报告.md" not in files
    assert "API - Parametric knowledge" in (output / "01-Audit-Report.md").read_text("utf-8")
    assert "Add sitemap.xml and submit it to international search engines" in (output / "03-Ticket-Log.md").read_text("utf-8")
    assert "Current value: 1; target: at most 0." in (output / "04-Acceptance-Checklist.md").read_text("utf-8")
    assert delivery.delivery_language_violations(output) == []


def test_delivery_contract_removes_domestic_questions_and_channels(tmp_path, monkeypatch):
    project, output = seed_delivery_project(tmp_path)
    config = json.loads((project / "geo.json").read_text("utf-8"))
    config["questions"] = [{"id": "q001", "text": "这个品牌是什么？", "market": "cn"}]
    _write_json(project / "geo.json", config)
    blueprint = json.loads((project / "blueprint.json").read_text("utf-8"))
    blueprint["contents"][0].update({"market": "cn", "question": "这个品牌是什么？"})
    blueprint["channels"].append({
        "id": "baike", "name": "Baidu Baike", "priority": "P0", "market": "cn", "covered": False,
    })
    _write_json(project / "blueprint.json", blueprint)
    _patch_project(monkeypatch, project)

    delivery.ensure_delivery_contract("example", output)

    build_map = (output / "06-Build-Map.md").read_text("utf-8")
    assert "这个品牌是什么" not in build_map
    assert "Baidu" not in build_map
    assert not (output / "assets" / "outlines" / "q001.md").exists()
    assert json.loads((project / "geo.json").read_text("utf-8"))["questions"] == []
    assert delivery.delivery_language_violations(output) == []


def test_delivery_contract_rebuilds_mixed_language_llms_asset(tmp_path, monkeypatch):
    project, output = seed_delivery_project(tmp_path)
    (project / "assets" / "llms.en.txt").write_text(
        "# Example\n\n> 中文品牌定义\n\n- Industry: 中文行业\n",
        "utf-8",
    )
    _patch_project(monkeypatch, project)

    delivery.ensure_delivery_contract("example", output)

    text = (output / "assets" / "llms.en.txt").read_text("utf-8")
    assert "# Example" in text
    assert "https://example.com" in text
    assert "approved one-sentence English brand definition" in text
    assert delivery.delivery_language_violations(output) == []


def test_delivery_contract_normalizes_generated_jsonld_values(tmp_path, monkeypatch):
    project, output = seed_delivery_project(tmp_path)
    _write_json(project / "assets" / "jsonld" / "faq-page.json", {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [{
            "@type": "Question",
            "name": "这个品牌是什么？",
            "acceptedAnswer": {"@type": "Answer", "text": "这里填写答案"},
        }],
    })
    _write_json(project / "assets" / "jsonld" / "software.json", {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": "Example",
        "description": "中文品牌定义",
        "offers": [{"@type": "Offer", "price": "79", "priceCurrency": "美元"}],
    })
    _patch_project(monkeypatch, project)

    delivery.ensure_delivery_contract("example", output)

    faq = json.loads((output / "assets" / "jsonld" / "faq-page.json").read_text("utf-8"))
    software = json.loads((output / "assets" / "jsonld" / "software.json").read_text("utf-8"))
    assert faq["mainEntity"][0]["name"] == "Configured Global target question 1"
    assert faq["mainEntity"][0]["acceptedAnswer"]["text"] == "[Add a direct English answer followed by supporting evidence.]"
    assert software["description"] == "[Add the approved English brand description.]"
    assert software["offers"][0]["priceCurrency"] == "USD"
    assert delivery.delivery_language_violations(output) == []


def test_language_validator_detects_paths_entities_and_json_escapes(tmp_path):
    output = tmp_path / "delivery"
    output.mkdir()
    (output / "中文.md").write_text("English", "utf-8")
    (output / "entity.html").write_text("&#x4e2d;&#x6587;", "utf-8")
    (output / "double-entity.html").write_text("&amp;#x4e2d;&amp;#x6587;", "utf-8")
    (output / "escaped.json").write_text(r'{"message": "\u4e2d\u6587"}', "utf-8")

    assert delivery.delivery_language_violations(output) == [
        "double-entity.html", "entity.html", "escaped.json", "中文.md",
    ]
    with pytest.raises(GeoEngineError, match="entity.html"):
        delivery.validate_delivery_language(output)


def test_delivery_contract_fails_closed_for_custom_chinese_asset(tmp_path, monkeypatch):
    project, output = seed_delivery_project(tmp_path)
    _patch_project(monkeypatch, project)
    custom = project / "assets" / "custom" / "notes.txt"
    custom.parent.mkdir()
    custom.write_text("不可翻译的客户资产", "utf-8")

    with pytest.raises(GeoEngineError, match="assets/custom/notes.txt"):
        delivery.ensure_delivery_contract("example", output)

    assert not output.exists()


def test_delivery_contract_preserves_custom_english_asset(tmp_path, monkeypatch):
    project, output = seed_delivery_project(tmp_path)
    _patch_project(monkeypatch, project)
    custom = project / "assets" / "outlines" / "customer-notes.txt"
    custom.write_text("Use the approved positioning statement.", "utf-8")

    delivery.ensure_delivery_contract("example", output)

    target = output / "assets" / "outlines" / "customer-notes.txt"
    assert target.read_text("utf-8") == "Use the approved positioning statement."
    assert delivery.delivery_language_violations(output) == []


def test_delivery_contract_rejects_missing_structured_source(tmp_path, monkeypatch):
    project, output = seed_delivery_project(tmp_path)
    _patch_project(monkeypatch, project)
    (project / "blueprint.json").unlink()

    with pytest.raises(GeoEngineError, match="blueprint.json"):
        delivery.ensure_delivery_contract("example", output)

    assert not output.exists()
