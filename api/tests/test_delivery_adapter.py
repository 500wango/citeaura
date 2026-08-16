import json
from pathlib import Path

import pytest

from api.adapters import brand_facts, delivery
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
            "question_id": "q001", "question": "What is Example?", "ok": True,
            "answer": "Example is an AI visibility platform.", "citations": [],
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


def _write_jsonl(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values), "utf-8")


def _patch_project(monkeypatch, project):
    monkeypatch.setattr(delivery.geolib, "project_dir", lambda slug: project)
    monkeypatch.setattr(delivery.geolib, "today", lambda: "2026-07-31")
    monkeypatch.setattr(delivery.geolib, "now_iso", lambda: "2026-07-31T12:00:00+00:00")
    monkeypatch.setattr(delivery.app_config, "source_revision", lambda: "abcdef123456")


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
    assert "abcdef123456" in (output / "README.md").read_text("utf-8")
    assert "abcdef123456" in (output / "index.md").read_text("utf-8")
    assert json.loads((output / "assets" / "index.json").read_text("utf-8"))["source_revision"] == "abcdef123456"
    assert "Add sitemap.xml and submit it to international search engines" in (output / "03-Ticket-Log.md").read_text("utf-8")
    assert "Current value: 1; target: at most 0." in (output / "04-Acceptance-Checklist.md").read_text("utf-8")
    assert delivery.delivery_language_violations(output) == []


def test_delivery_audit_uses_page_role_applicability(tmp_path, monkeypatch):
    project, output = seed_delivery_project(tmp_path)
    audit = json.loads((project / "audit.json").read_text("utf-8"))
    contact_url = "https://example.com/contact"
    audit["pages"][0].update({
        "url": contact_url,
        "title": "Contact",
        "word_count": 44,
        "issue_codes": [
            "SHORT_CONTENT", "FEW_H2", "NO_DEFINITION", "NO_NUMBERS",
            "NO_COMPARISON", "NO_HOWTO", "NO_FAQ", "NO_DATE",
            "FEW_EXTERNAL_LINKS", "NO_JSONLD", "LOW_RELEVANCE",
        ],
    })
    _write_json(project / "audit.json", audit)
    _write_jsonl(project / "evidence" / "pages.jsonl", [{
        "url": contact_url,
        "status": 200,
        "title": "Contact",
        "meta_robots": "",
        "canonical": contact_url,
        "h1": ["Contact"],
        "h2": [],
        "para_count": 3,
        "word_count": 44,
        "external_links": 0,
        "jsonld_types": [],
        "text": "Contact our sales and support teams.",
    }])
    _patch_project(monkeypatch, project)

    delivery.ensure_delivery_contract("example", output)

    report = (output / "01-Audit-Report.md").read_text("utf-8")
    execution = (output / "02-Execution-Plan.md").read_text("utf-8")
    tickets = (output / "03-Ticket-Log.md").read_text("utf-8")
    verification = (output / "04-Acceptance-Checklist.md").read_text("utf-8")
    assert "Applicable site score: **Not measured**" in report
    assert "only evidence-backed checks applicable to each page role" in report
    assert "Missing definition block" not in report
    assert "Missing FAQ block" not in report
    assert "| Not scored | 44 | - |" in report
    assert "Baseline site score: Not measured" in execution
    assert "Add clear definitions to applicable pages" in tickets
    assert "Re-audit applicable score: Not measured" in verification
    assert "T-002" in verification
    assert delivery.delivery_language_violations(output) == []


def test_delivery_allows_a_fully_compliant_project_with_no_action_tickets(tmp_path, monkeypatch):
    project, output = seed_delivery_project(tmp_path)
    audit = json.loads((project / "audit.json").read_text("utf-8"))
    audit.update({"avg_score": 100, "grade_distribution": {"A": 1, "B": 0, "C": 0, "D": 0}})
    audit["site"].update({"has_sitemap": True, "has_llms_txt": True, "ai_bots_blocked": []})
    audit["pages"][0].update({
        "url": "https://example.com/contact",
        "title": "Contact",
        "score": 100,
        "grade": "A",
        "issue_codes": [],
        "blocks": {},
    })
    _write_json(project / "audit.json", audit)
    _write_json(project / "tasks.json", {
        "generated_at": "2026-07-31T12:00:00+00:00",
        "baseline": {"avg_score": 100, "pages": 1},
        "tasks": [],
    })
    _write_jsonl(project / "evidence" / "pages.jsonl", [{
        "url": "https://example.com/contact",
        "final_url": "https://example.com/contact",
        "status": 200,
        "title": "Contact",
        "meta_robots": "index,follow",
        "canonical": "https://example.com/contact",
        "h1": ["Contact"],
        "h2": [],
        "para_count": 2,
        "word_count": 40,
        "external_links": 0,
        "jsonld_types": [],
        "text": "Contact the Example team for product and account enquiries.",
    }])
    monkeypatch.setattr(delivery.measurement, "sampling_quality", lambda slug: {
        "current": {"effective_visibility_samples": 40, "platform_count": 2},
        "confidence": {"sufficient": True, "label": "Representative baseline"},
    })
    _patch_project(monkeypatch, project)

    delivery.ensure_delivery_contract("example", output)

    execution = (output / "02-Execution-Plan.md").read_text("utf-8")
    tickets = (output / "03-Ticket-Log.md").read_text("utf-8")
    assert "Total tickets: 0" in execution
    assert "No unresolved action tickets for the current evidence" in tickets
    assert delivery.delivery_language_violations(output) == []


def test_legacy_deliverables_render_manual_channels_without_key_gap_status(tmp_path, monkeypatch):
    project, _output = seed_delivery_project(tmp_path)
    legacy = project / "deliverables"
    legacy.mkdir()
    (legacy / "1-GEO诊断报告.md").write_text("preserved audit", "utf-8")
    (legacy / "3-GEO执行方案.md").write_text("preserved execution plan", "utf-8")
    (legacy / "2-GEO优化方案.md").write_text("\n".join([
        "# Example GEO Strategy & Optimization Plan",
        "",
        "## 3. High-Leverage Opportunities",
        "",
        "preserved opportunities",
        "",
        "## 4. Platform & Content Blueprint",
        "",
        "Key gaps requiring immediate focus:",
        "",
        "raw engine output",
        "",
        "## 5. Resource Allocation Recommendations",
        "",
        "preserved resource guidance",
        "",
    ]), "utf-8")
    config = json.loads((project / "geo.json").read_text("utf-8"))
    config["brand"]["industry"] = "B2B SaaS software platform"
    _write_json(project / "geo.json", config)
    _patch_project(monkeypatch, project)

    result = delivery.ensure_legacy_deliverables_contract("example")

    assert result == legacy
    optimization = (legacy / "2-GEO优化方案.md").read_text("utf-8")
    assert "raw engine output" not in optimization
    assert "Key gaps requiring immediate focus" not in optimization
    assert "preserved opportunities" in optimization
    assert "preserved resource guidance" in optimization
    assert "| P0 | Product Documentation and API Reference | Global | Manual review |" in optimization
    assert "| P0 | Product Documentation and API Reference | Global | Gap |" not in optimization
    assert "Manual review" in (legacy / "2-GEO优化方案.html").read_text("utf-8")
    assert (legacy / "1-GEO诊断报告.md").read_text("utf-8") == "preserved audit"
    assert (legacy / "3-GEO执行方案.md").read_text("utf-8") == "preserved execution plan"


def test_legacy_deliverables_preserve_engine_output_without_blueprint(tmp_path, monkeypatch):
    project, _output = seed_delivery_project(tmp_path)
    legacy = project / "deliverables"
    legacy.mkdir()
    raw = legacy / "2-GEO优化方案.md"
    raw.write_text("raw engine output", "utf-8")
    (project / "blueprint.json").unlink()
    _patch_project(monkeypatch, project)

    assert delivery.ensure_legacy_deliverables_contract("example") == legacy
    assert raw.read_text("utf-8") == "raw engine output"


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

    text = (output / "assets" / "templates" / "llms.en.txt").read_text("utf-8")
    assert "# Example" in text
    assert "https://example.com" in text
    assert "approved one-sentence English brand definition" in text
    assert delivery.delivery_language_violations(output) == []


def test_delivery_contract_normalizes_generated_jsonld_values(tmp_path, monkeypatch):
    project, output = seed_delivery_project(tmp_path)
    config = json.loads((project / "geo.json").read_text("utf-8"))
    config["brand"]["industry"] = "B2B SaaS software platform"
    _write_json(project / "geo.json", config)
    _write_jsonl(project / "evidence" / "pages.jsonl", [{
        "url": "https://example.com", "status": 200,
        "text": "Example is a web software application for business teams.",
        "jsonld_types": ["SoftwareApplication"],
    }])
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

    faq = json.loads((output / "assets" / "templates" / "jsonld" / "faq-page.json").read_text("utf-8"))
    software = json.loads((output / "assets" / "templates" / "jsonld" / "software.json").read_text("utf-8"))
    assert faq["mainEntity"][0]["name"] == "What is Example?"
    assert faq["mainEntity"][0]["acceptedAnswer"]["text"] == "[Add a direct English answer followed by supporting evidence.]"
    assert software["description"] == "[Add the approved English brand description.]"
    assert software["offers"][0]["priceCurrency"] == "USD"
    assert delivery.delivery_language_violations(output) == []


def test_delivery_rejects_ambiguous_offer_values_from_ready_assets(tmp_path, monkeypatch):
    project, output = seed_delivery_project(tmp_path)
    config = json.loads((project / "geo.json").read_text("utf-8"))
    config["brand"]["industry"] = "B2B SaaS software platform"
    _write_json(project / "geo.json", config)
    _write_jsonl(project / "evidence" / "pages.jsonl", [{
        "url": "https://example.com", "status": 200,
        "text": "Example is a web software application for business teams.",
        "jsonld_types": ["SoftwareApplication"],
    }])
    _write_json(project / "assets" / "jsonld" / "software-application.json", {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": "Example",
        "url": "https://example.com",
        "description": "Example is a business application.",
        "offers": [{"@type": "Offer", "price": "$79 / month", "priceCurrency": "$"}],
    })
    _patch_project(monkeypatch, project)

    delivery.ensure_delivery_contract("example", output)

    index = json.loads((output / "assets" / "index.json").read_text("utf-8"))
    record = next(item for item in index["assets"] if item["path"].endswith("software-application.json"))
    decision = next(item for item in index["schema_selection"]["included"] if item["path"].endswith("software-application.json"))
    assert record["status"] == "template"
    assert record["path"] == "templates/jsonld/software-application.json"
    assert "Offer price must be a non-negative machine-readable number" in record["issues"]
    assert "Offer priceCurrency must be an ISO 4217 code" in record["issues"]
    assert decision["path"] == record["path"]
    assert not (output / "assets" / "jsonld" / "software-application.json").exists()


def test_delivery_reuses_unreviewed_brand_facts_as_review_drafts(tmp_path, monkeypatch):
    project, output = seed_delivery_project(tmp_path)
    config = json.loads((project / "geo.json").read_text("utf-8"))
    config["brand"].update({
        "industry": "Industrial operations software",
        "target_users": "Distributed field operations teams",
        "products": ["Work order coordination", "Operational reporting"],
    })
    config["competitors"] = []
    _write_json(project / "geo.json", config)
    (project / "content").mkdir()
    _patch_project(monkeypatch, project)
    facts = brand_facts.render_facts_data("example", {
        "name": "Example",
        "industry": "Industrial operations software",
        "definition": "Example coordinates field operations for distributed industrial teams.",
        "products": ["Work order coordination", "Operational reporting"],
        "target_users": "Distributed field operations teams",
        "business_goal": "Qualified product enquiries (inferred)",
        "key_numbers": [{"fact": "Supported regions", "value": "18", "source": "Official website"}],
        "suitable": ["Multi-site field operations"],
        "unsuitable": ["Unverified medical workflows"],
    })
    (project / "content" / "facts.md").write_text(facts, "utf-8")
    (project / "assets" / "llms.en.txt").write_text(
        "# Example\n\n> Example coordinates field operations for distributed industrial teams.\n\n- Industry: Industrial operations software\n",
        "utf-8",
    )
    _write_json(project / "assets" / "jsonld" / "organization.json", {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "Example",
        "url": "https://example.com",
    })

    delivery.ensure_delivery_contract("example", output)

    index = json.loads((output / "assets" / "index.json").read_text("utf-8"))
    records = {item["path"]: item for item in index["assets"]}
    assert records["drafts/brand-facts.md"]["status"] == "needs_review"
    assert records["llms.en.txt"]["status"] == "needs_review"
    assert records["jsonld/organization.json"]["status"] == "needs_review"
    assert records["snippets/definition.en.html"]["status"] == "needs_review"
    assert "Derived from an unreviewed brand facts library" in records["llms.en.txt"]["issues"]
    assert "Derived from an unreviewed brand facts library" in records["jsonld/organization.json"]["issues"]
    assert "Derived from an unreviewed brand facts library" in records["snippets/definition.en.html"]["issues"]
    llms = (output / "assets" / "llms.en.txt").read_text("utf-8")
    assert "Example coordinates field operations" in llms
    assert "[Add" not in llms
    assert "Industrial operations software" in llms


def test_delivery_omits_specialized_schema_without_project_evidence(tmp_path, monkeypatch):
    project, output = seed_delivery_project(tmp_path)
    _write_json(project / "assets" / "jsonld" / "unsupported-software.json", {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": "Example",
        "url": "https://example.com",
        "description": "A business application.",
    })
    _patch_project(monkeypatch, project)

    delivery.ensure_delivery_contract("example", output)

    assert not any(path.name == "unsupported-software.json" for path in output.rglob("*.json"))
    index = json.loads((output / "assets" / "index.json").read_text("utf-8"))
    omitted = index["schema_selection"]["omitted"]
    assert omitted == [{
        "path": "jsonld/unsupported-software.json",
        "status": "omitted",
        "types": ["SoftwareApplication"],
        "reason": "No project evidence supports specialized Schema.org type(s): SoftwareApplication",
        "evidence": [],
        "requires_review": False,
    }]


def test_delivery_accepts_any_confirmed_specialized_schema_type(tmp_path, monkeypatch):
    project, output = seed_delivery_project(tmp_path)
    config = json.loads((project / "geo.json").read_text("utf-8"))
    config["schema_types"] = [{"type": "MedicalDevice", "confirmed": True}]
    _write_json(project / "geo.json", config)
    _write_json(project / "assets" / "jsonld" / "medical-device.json", {
        "@context": "https://schema.org",
        "@type": "MedicalDevice",
        "name": "Example Monitor",
    })
    _patch_project(monkeypatch, project)

    delivery.ensure_delivery_contract("example", output)

    assert (output / "assets" / "jsonld" / "medical-device.json").is_file()
    index = json.loads((output / "assets" / "index.json").read_text("utf-8"))
    decision = next(
        item for item in index["schema_selection"]["included"]
        if item["path"] == "jsonld/medical-device.json"
    )
    assert decision["evidence"][0]["source"] == "project_config"
    assert decision["requires_review"] is False


def test_delivery_marks_high_confidence_inferred_schema_for_confirmation(tmp_path, monkeypatch):
    project, output = seed_delivery_project(tmp_path)
    config = json.loads((project / "geo.json").read_text("utf-8"))
    config["brand"]["industry"] = "B2B SaaS software platform"
    _write_json(project / "geo.json", config)
    _write_jsonl(project / "evidence" / "pages.jsonl", [{
        "url": "https://example.com/product", "status": 200,
        "text": "Example is a cloud software platform and web application for operations teams.",
    }])
    _write_json(project / "assets" / "jsonld" / "inferred-software.json", {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": "Example",
        "url": "https://example.com",
        "description": "Cloud operations software.",
    })
    _patch_project(monkeypatch, project)

    delivery.ensure_delivery_contract("example", output)

    index = json.loads((output / "assets" / "index.json").read_text("utf-8"))
    records = {item["path"]: item for item in index["assets"]}
    record = records["jsonld/inferred-software.json"]
    assert record["status"] == "needs_review"
    assert "Schema applicability is inferred and requires confirmation" in record["issues"]
    decision = next(
        item for item in index["schema_selection"]["included"]
        if item["path"] == "jsonld/inferred-software.json"
    )
    assert decision["requires_review"] is True
    assert decision["evidence"][0]["source"] == "business_profile"


def test_delivery_manifest_separates_ready_review_and_template_assets(tmp_path, monkeypatch):
    project, output = seed_delivery_project(tmp_path)
    _write_json(project / "assets" / "jsonld" / "organization-ready.json", {
        "@context": "https://schema.org", "@type": "Organization", "name": "Example",
        "url": "https://example.com", "sameAs": [],
    })
    draft = project / "assets" / "drafts" / "q001.md"
    draft.parent.mkdir(parents=True)
    draft.write_text("# What is Example?\n\nExample is a software platform. Verify this claim before publication.\n", "utf-8")
    _patch_project(monkeypatch, project)

    delivery.ensure_delivery_contract("example", output)

    index = json.loads((output / "assets" / "index.json").read_text("utf-8"))
    records = {item["path"]: item for item in index["assets"]}
    assert index["readiness"] == "review_required"
    assert records["jsonld/organization-ready.json"]["status"] == "ready"
    assert records["drafts/q001.md"]["status"] == "needs_review"
    assert records["templates/llms.en.txt"]["status"] == "template"
    assert "Contains unresolved placeholders" in records["templates/llms.en.txt"]["issues"]
    assert "Ready to deploy" in (output / "index.md").read_text("utf-8")


def test_delivery_manifest_rejects_jsonld_path_placeholders(tmp_path, monkeypatch):
    project, output = seed_delivery_project(tmp_path)
    _write_json(project / "assets" / "jsonld" / "breadcrumb.json", {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [{
            "@type": "ListItem", "position": 1,
            "name": "<section>", "item": "https://example.com/<path>",
        }],
    })
    _patch_project(monkeypatch, project)

    delivery.ensure_delivery_contract("example", output)

    index = json.loads((output / "assets" / "index.json").read_text("utf-8"))
    records = {item["path"]: item for item in index["assets"]}
    record = records["templates/jsonld/breadcrumb.json"]
    assert record["status"] == "template"
    assert "Contains unresolved placeholders" in record["issues"]
    assert not (output / "assets" / "jsonld" / "breadcrumb.json").exists()


def test_delivery_labels_english_pages_as_content_threshold(tmp_path, monkeypatch):
    project, output = seed_delivery_project(tmp_path)
    _patch_project(monkeypatch, project)

    delivery.ensure_delivery_contract("example", output)

    report = (output / "01-Audit-Report.md").read_text("utf-8")
    assert "English content pages (120+ words)" in report


def test_delivery_outlines_are_specific_to_question_intent(tmp_path, monkeypatch):
    project, output = seed_delivery_project(tmp_path)
    blueprint = json.loads((project / "blueprint.json").read_text("utf-8"))
    blueprint["contents"] = [
        {
            "id": "q001", "market": "global", "group": "comparison",
            "question": "How does Example compare with Acme?", "form": "Comparison page", "status": "gap",
        },
        {
            "id": "q002", "market": "global", "group": "pricing",
            "question": "How much does Example cost?", "form": "Pricing guide", "status": "gap",
        },
    ]
    _write_json(project / "blueprint.json", blueprint)
    _patch_project(monkeypatch, project)

    delivery.ensure_delivery_contract("example", output)

    comparison = (output / "assets" / "templates" / "outlines" / "q001.md").read_text("utf-8")
    pricing = (output / "assets" / "templates" / "outlines" / "q002.md").read_text("utf-8")
    assert "Criterion-by-criterion comparison" in comparison
    assert "Worked cost scenarios" in pricing
    assert comparison != pricing


def test_language_validator_detects_paths_entities_and_json_escapes(tmp_path):
    output = tmp_path / "delivery"
    output.mkdir()
    (output / "中文.md").write_text("English", "utf-8")
    (output / "entity.html").write_text("&#x4e2d;&#x6587;", "utf-8")
    (output / "double-entity.html").write_text("&amp;#x4e2d;&amp;#x6587;", "utf-8")
    (output / "escaped.json").write_text(r'{"message": "\u4e2d\u6587"}', "utf-8")
    (output / "cjk-punctuation.txt").write_text("GPTBot、ClaudeBot", "utf-8")
    (output / "fullwidth.json").write_text(r'{"message": "Review\uff1arequired"}', "utf-8")
    (output / "legitimate.txt").write_text("Coverage ≥ 95%; USD $10–20; API - Search grounded.", "utf-8")

    assert delivery.delivery_language_violations(output) == [
        "cjk-punctuation.txt", "double-entity.html", "entity.html", "escaped.json", "fullwidth.json", "中文.md",
    ]
    with pytest.raises(GeoEngineError, match="entity.html"):
        delivery.validate_delivery_language(output)


def test_delivery_normalizes_dynamic_cjk_punctuation_in_english_documents(tmp_path, monkeypatch):
    project, output = seed_delivery_project(tmp_path)
    audit = json.loads((project / "audit.json").read_text("utf-8"))
    audit["site"]["ai_bots_blocked"] = ["GPTBot", "ClaudeBot", "Bytespider", "Google-Extended"]
    _write_json(project / "audit.json", audit)
    tasks = json.loads((project / "tasks.json").read_text("utf-8"))
    tasks["tasks"][0].update({
        "title": "解除 robots.txt 对 AI 抓取器的封禁",
        "why": "robots 封禁 GPTBot、ClaudeBot、Bytespider、Google-Extended，这些引擎永远抓不到你（method.md 可抓取性）",
        "action": "移除对应 Disallow，或改为仅屏蔽后台路径",
        "acceptance": {
            "type": "auto", "check": "site.no_ai_bot_block",
            "desc": "重抓后 robots 不再整站封禁任何 AI 抓取器",
        },
    })
    _write_json(project / "tasks.json", tasks)
    _patch_project(monkeypatch, project)

    delivery.ensure_delivery_contract("example", output)

    for name in ("02-Execution-Plan.md", "03-Ticket-Log.md", "03-Ticket-Log.csv"):
        text = (output / name).read_text("utf-8")
        assert "GPTBot, ClaudeBot, Bytespider, Google-Extended" in text
        assert "、" not in text
    assert delivery.delivery_language_violations(output) == []


def test_delivery_contract_fails_closed_for_custom_chinese_asset(tmp_path, monkeypatch):
    project, output = seed_delivery_project(tmp_path)
    _patch_project(monkeypatch, project)
    custom = project / "assets" / "custom" / "notes.txt"
    custom.parent.mkdir()
    custom.write_text("不可翻译的客户资产", "utf-8")

    with pytest.raises(GeoEngineError, match="assets/custom/notes.txt"):
        delivery.ensure_delivery_contract("example", output)

    assert output.exists()


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

    assert output.exists()


def test_delivery_corrects_financial_question_intent_and_outline_structure(tmp_path, monkeypatch):
    project, output = seed_delivery_project(tmp_path)
    blueprint = json.loads((project / "blueprint.json").read_text("utf-8"))
    blueprint["contents"] = [
        {
            "id": "q111", "market": "global", "group": "brand_verification",
            "question": "Is Example a legitimate and safe app for international money transfers?",
            "form": "About Us & Knowledge Graph", "status": "gap",
        },
        {
            "id": "q112", "market": "global", "group": "brand_verification",
            "question": "What fees, exchange rates, and withdrawal limits does Example have?",
            "form": "About Us & Knowledge Graph", "status": "gap",
        },
        {
            "id": "q114", "market": "global", "group": "scenario",
            "question": "What app should I use to send money and withdraw cash while I travel?",
            "form": "How-To Tutorial Page", "status": "gap",
        },
        {
            "id": "q115", "market": "global", "group": "scenario",
            "question": "Compare Example vs. another provider for international transfers.",
            "form": "How-To Tutorial Page", "status": "gap",
        },
    ]
    _write_json(project / "blueprint.json", blueprint)
    for content_id in ("q111", "q112", "q114", "q115"):
        (project / "assets" / "outlines" / f"{content_id}.md").write_text("# Source outline\n", "utf-8")
    _patch_project(monkeypatch, project)

    delivery.ensure_delivery_contract("example", output)

    build_map = (output / "06-Build-Map.md").read_text("utf-8")
    risk = (output / "assets" / "templates" / "outlines" / "q111.md").read_text("utf-8")
    pricing = (output / "assets" / "templates" / "outlines" / "q112.md").read_text("utf-8")
    recommendation = (output / "assets" / "templates" / "outlines" / "q114.md").read_text("utf-8")
    assert "Trust, Regulation, and Safeguarding Page" in build_map
    assert "Transparent Pricing and Fees Page" in build_map
    assert "Evidence-Based Recommendation Page" in build_map
    assert "Comparison Matrix Page" in build_map
    assert "Regulatory authorization and register evidence" in risk
    assert "Transfer, exchange-rate, card, ATM, and withdrawal fee components" in pricing
    assert "Intent: Recommendation" in recommendation


def test_delivery_risk_report_and_llms_ticket_propagate_unreviewed_fact_status(tmp_path, monkeypatch):
    project, output = seed_delivery_project(tmp_path)
    _patch_project(monkeypatch, project)
    (project / "content").mkdir()
    facts = brand_facts.render_facts_data("example", {
        "name": "Example",
        "industry": "Financial services",
        "definition": "Example provides international payment services.",
        "products": ["International transfers"],
        "target_users": "International consumers",
        "pricing": [{"name": "Card", "price": "$9.99/month", "currency": "$"}],
    })
    (project / "content" / "facts.md").write_text(facts, "utf-8")
    tasks = json.loads((project / "tasks.json").read_text("utf-8"))
    tasks["tasks"].append({
        "id": "T-LLMS", "priority": "P1", "package": "Knowledge base", "market": "global",
        "title": "Deploy llms", "why": "Missing", "action": "Deploy /llms.txt", "owner": "Engineering",
        "effort": "S", "window": "60 days", "affected": [],
        "acceptance": {"type": "auto", "check": "site.has_llms_txt", "desc": "Fetch it"}, "status": "todo",
    })
    _write_json(project / "tasks.json", tasks)

    delivery.ensure_delivery_contract("example", output)

    execution = (output / "02-Execution-Plan.md").read_text("utf-8")
    risks = (output / "05-Draft-Risks.md").read_text("utf-8")
    manifest = json.loads((output / "assets" / "index.json").read_text("utf-8"))
    delivered_facts = (output / "assets" / "drafts" / "brand-facts.md").read_text("utf-8")
    assert "Brand facts library has passed factual review (Pending)" in execution
    assert "Execution state: Blocked until all prerequisites are met" in execution
    assert "assets/drafts/brand-facts.md" in risks
    assert "assets/drafts/llms.en.txt" in risks
    assert manifest["quality_gate"]["status"] == "passed"
    assert "$9.99/month $" not in delivered_facts


def test_delivery_low_score_coverage_is_explicit_in_html_and_score_ticket(tmp_path, monkeypatch):
    project, output = seed_delivery_project(tmp_path)
    audit = json.loads((project / "audit.json").read_text("utf-8"))
    audit["pages"].extend([
        {
            **audit["pages"][0],
            "url": f"https://example.com/unreachable-{index}",
            "title": "Unavailable page",
            "word_count": 0,
            "issue_codes": ["PAGE_UNREACHABLE"],
        }
        for index in range(4)
    ])
    audit["page_count"] = len(audit["pages"])
    _write_json(project / "audit.json", audit)
    tasks = json.loads((project / "tasks.json").read_text("utf-8"))
    tasks["tasks"].append({
        "id": "T-SCORE", "priority": "P1", "package": "Site quality", "market": "global",
        "title": "Raise score", "why": "Raw score is low", "action": "Fix everything",
        "owner": "Engineering", "effort": "M", "window": "60 days", "affected": [],
        "acceptance": {"type": "auto", "check": "site.avg_score_gte:70", "desc": "Score reaches 70"},
        "status": "todo",
    })
    _write_json(project / "tasks.json", tasks)
    _patch_project(monkeypatch, project)

    delivery.ensure_delivery_contract("example", output)

    audit_markdown = (output / "01-Audit-Report.md").read_text("utf-8")
    audit_html = (output / "01-Audit-Report.html").read_text("utf-8")
    tickets = (output / "03-Ticket-Log.md").read_text("utf-8")
    acceptance = (output / "04-Acceptance-Checklist.md").read_text("utf-8")
    assert "Not reported (partial result:" in audit_markdown
    assert "Scoring coverage: **1/5 eligible pages (20.0%)**" in audit_markdown
    assert "Not reported (partial result:" in audit_html
    assert "Scoring Coverage" in audit_html
    assert "20.0%" in audit_html
    assert "score is None" not in tickets
    assert "Role-aware scoring coverage reaches at least 80% (Pending)" in tickets
    assert "site score is withheld" in acceptance
    assert "Re-audit applicable score: Not reported (partial result:" in acceptance
    assert "Re-audit scoring coverage: 20.0%" in acceptance
