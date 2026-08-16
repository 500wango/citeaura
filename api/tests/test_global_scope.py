import json
from copy import deepcopy

from api.adapters import delivery, global_scope

import blueprint as engine_blueprint  # noqa: E402 - global_scope registers the engine scripts path first


def _engine_global_blueprint():
    channels = []
    for channel in deepcopy(engine_blueprint.CHANNELS_GLOBAL):
        channel.update({
            "market": "global",
            "covered": channel["id"] in ("official_en", "youtube"),
            "fits": deepcopy(engine_blueprint.CHANNEL_FITS.get(channel["id"], [])),
        })
        channels.append(channel)
    return {
        "market": "global",
        "channels": channels,
        "contents": [{
            "id": "q101", "market": "global", "question": "Which tool is best?",
            "group": "recommendation", "form": "Category Page", "status": "gap", "note": "",
        }],
    }


def test_mixed_historical_config_is_normalized_to_global():
    config = {
        "market": "both",
        "platforms": ["glm", "deepseek", "openai", "chatgpt", "custom_gateway"],
        "questions": [
            {"id": "q001", "market": "cn", "text": "哪个工具更好？", "group": "推荐"},
            {"id": "q101", "market": "global", "text": "Which tool is best?", "group": "recommendation"},
            {"id": "q901", "market": "both", "text": "What is CiteAura?", "group": "品牌验证"},
            {"id": "q902", "market": "both", "text": "CiteAura 是什么？", "group": "品牌验证"},
        ],
        "competitors": [
            {"name": "Domestic Rival", "market": "cn"},
            {
                "name": "Global Rival", "market": "global",
                "relationship": "direct_competitor", "relationship_source": "user",
            },
            {
                "name": "Universal Rival", "market": "both",
                "relationship": "direct_competitor", "relationship_source": "user",
            },
        ],
    }

    normalized = global_scope.normalize_config_data(config)

    assert normalized["market"] == "global"
    assert normalized["platforms"] == ["openai", "chatgpt", "custom_gateway"]
    assert [question["id"] for question in normalized["questions"]] == ["q101", "q901"]
    assert all(question["market"] == "global" for question in normalized["questions"])
    assert normalized["questions"][1]["group"] == "brand_verification"
    assert [item["name"] for item in normalized["competitors"]] == ["Global Rival", "Universal Rival"]


def test_blueprint_and_tasks_remove_domestic_recommendations():
    blueprint = global_scope.normalize_blueprint_data({
        "market": "both",
        "channels": [
            {"id": "baike", "name": "Baidu Baike", "market": "cn", "priority": "P0", "covered": True},
            {"id": "wikipedia", "name": "Wikipedia", "market": "global", "priority": "P1", "covered": False},
            {"id": "review", "name": "G2", "market": "global", "priority": "P1", "covered": True},
            {"id": "reddit", "name": "Reddit", "market": "global", "priority": "P1", "covered": False},
            {"id": "youtube", "name": "YouTube", "market": "global", "priority": "P1", "covered": False},
        ],
        "contents": [
            {"id": "q001", "market": "cn", "question": "哪个好？", "status": "gap"},
            {"id": "q101", "market": "global", "question": "Which one is best?", "status": "ready"},
        ],
    })
    tasks = global_scope.normalize_tasks_data({
        "market": "both",
        "tasks": [
            {"id": "T-001", "market": "cn", "title": "拿下榜单/品牌库站词条", "status": "todo"},
            {
                "id": "T-002", "market": "both", "title": "补 sitemap.xml 并提交各搜索引擎",
                "status": "todo", "priority": "P0", "package": "页面技术", "acceptance": {"type": "auto"},
            },
            {
                "id": "T-003", "market": "both", "title": "百科词条（实体消歧地基）",
                "status": "todo", "priority": "P1", "package": "知识库", "acceptance": {"type": "manual"},
            },
        ],
    })

    assert [channel["id"] for channel in blueprint["channels"]] == ["wikipedia", "review", "reddit", "youtube"]
    assert blueprint["coverage"] == {
        "channel_all_total": 4,
        "channel_total": 4,
        "channel_covered": 1,
        "channel_observed": 0,
        "channel_manual": 0,
        "channel_rate": 0.25,
        "p0p1_total": 4,
        "p0p1_covered": 1,
        "p0p1_manual": 0,
        "content_total": 1,
        "content_done": 1,
        "content_rate": 1.0,
        "content_gap": 0,
    }
    roadmap = "\n".join(item for phase in blueprint["roadmap"] for item in phase["items"])
    assert all(name in roadmap for name in ("Wikipedia", "G2 / Capterra / Product Hunt", "Reddit / Hacker News", "YouTube"))
    assert [task["id"] for task in tasks["tasks"]] == ["T-002", "T-003"]
    assert "Google and Bing" in tasks["tasks"][0]["action"]
    assert tasks["tasks"][1]["title"] == "Assess independent-source notability before encyclopedia work"
    assert "If the threshold is not met" in tasks["tasks"][1]["action"]
    assert all(task["market"] == "global" for task in tasks["tasks"])


def test_channel_strategy_is_selected_per_project_profile():
    manufacturer = global_scope.infer_business_profile({
        "brand": {"industry": "Laundry detergent OEM/ODM manufacturer"},
    })
    software = global_scope.infer_business_profile({
        "brand": {"industry": "B2B SaaS software platform", "products": ["API"]},
    })
    service = global_scope.infer_business_profile({
        "brand": {"industry": "Professional consulting services"},
    })
    financial = global_scope.infer_business_profile({
        "brand": {"industry": "Global payments and multi-currency financial services app"},
    })
    unknown = global_scope.infer_business_profile({"brand": {"industry": ""}})
    evidenced_software = global_scope.infer_business_profile(
        {"brand": {"industry": "B2B SaaS software platform"}},
        pages=[{
            "url": "https://example.com/product", "status": 200,
            "text": "Example is a cloud software platform and web application for operations teams.",
        }],
    )
    incidental_keyword = global_scope.infer_business_profile(
        {"brand": {"industry": ""}},
        pages=[{
            "url": "https://example.com/news", "status": 200,
            "text": "Visit our newsroom for company announcements and press enquiries.",
        }],
    )

    assert manufacturer["id"] == "manufacturer"
    assert software["id"] == "software"
    assert service["id"] == "service"
    assert financial["id"] == "financial_services"
    assert unknown["id"] == "generic"
    assert unknown["confidence"] == "low"
    assert unknown["review_required"] is True
    assert unknown["candidates"] == []
    assert evidenced_software["id"] == "software"
    assert evidenced_software["confidence"] == "high"
    assert evidenced_software["confirmed"] is False
    assert evidenced_software["review_required"] is True
    assert evidenced_software["evidence_details"][0]["url"] == "https://example.com/product"
    assert "software platform" in evidenced_software["evidence_details"][0]["excerpt"].lower()
    assert incidental_keyword["id"] == "generic"
    assert incidental_keyword["candidates"][0]["id"] == "publisher"
    assert incidental_keyword["candidates"][0]["evidence"][0]["url"] == "https://example.com/news"

    manufacturer_blueprint = global_scope.normalize_blueprint_data({}, profile=manufacturer)
    software_blueprint = global_scope.normalize_blueprint_data({}, profile=software)
    unknown_blueprint = global_scope.normalize_blueprint_data({}, profile=unknown)
    manufacturer_ids = {item["id"] for item in manufacturer_blueprint["channels"]}
    software_ids = {item["id"] for item in software_blueprint["channels"]}
    unknown_ids = {item["id"] for item in unknown_blueprint["channels"]}

    assert {"b2b_marketplaces", "certification", "trade_media"} <= manufacturer_ids
    assert "review" not in manufacturer_ids
    assert {"docs", "review", "developer_community"} <= software_ids
    assert "reddit" in manufacturer_ids & software_ids & unknown_ids
    assert "b2b_marketplaces" not in software_ids
    assert "industry_directories" in unknown_ids
    assert unknown_blueprint["channel_strategy"]["confidence"] == "low"

    financial_blueprint = global_scope.normalize_blueprint_data({}, profile=financial)
    financial_ids = {item["id"] for item in financial_blueprint["channels"]}
    assert {"regulatory_registries", "app_stores", "finance_comparison"} <= financial_ids


def test_repeated_financial_website_evidence_can_select_a_reviewable_profile():
    profile = global_scope.infer_business_profile(
        {"brand": {"industry": ""}},
        pages=[
            {"url": "https://example.com", "status": 200, "text": "A multi-currency payment app for money transfers."},
            {"url": "https://example.com/transfers", "status": 200, "text": "Send money internationally with foreign exchange support."},
        ],
    )

    assert profile["id"] == "financial_services"
    assert profile["confidence"] == "medium"
    assert profile["review_required"] is True


def test_crawl_deduplication_preserves_query_pages_with_different_content():
    shared = "Contact the sales team for a general request."
    pages = [
        {
            "url": "https://example.com/contact", "final_url": "https://example.com/contact",
            "canonical": "/contact", "status": 200, "text": shared, "word_count": 9,
        },
        {
            "url": "https://example.com/contact?source=%2Fen&interest=General+RFQ",
            "final_url": "https://example.com/contact?source=%2Fen&interest=General+RFQ",
            "canonical": "https://example.com/contact", "status": 200,
            "text": "  Contact the sales team for a general request.  ", "word_count": 9,
        },
        {
            "url": "https://example.com/contact?department=support",
            "final_url": "https://example.com/contact?department=support",
            "canonical": "https://example.com/contact", "status": 200,
            "text": "Open a technical support case with diagnostic details.", "word_count": 9,
        },
    ]

    deduplicated = global_scope.deduplicate_crawl_pages(pages)

    assert [page["url"] for page in deduplicated] == [
        "https://example.com/contact",
        "https://example.com/contact?department=support",
    ]
    assert deduplicated[0]["duplicate_urls"] == [
        "https://example.com/contact?source=%2Fen&interest=General+RFQ",
    ]


def test_audit_is_recomputed_from_deduplicated_evidence(tmp_path, monkeypatch):
    project = tmp_path / "example"
    evidence = project / "evidence"
    evidence.mkdir(parents=True)
    (project / "geo.json").write_text(json.dumps({
        "slug": "example",
        "market": "global",
        "brand": {"name": "Example", "site": "https://example.com", "aliases": [], "products": []},
        "questions": [],
    }), "utf-8")
    repeated = " ".join(["verified contact information"] * 45)
    pages = [
        {
            "url": "https://example.com/contact", "final_url": "https://example.com/contact",
            "canonical": "https://example.com/contact", "status": 200, "text": repeated,
            "word_count": 135, "title": "Contact", "h1": ["Contact"], "h2": [],
        },
        {
            "url": "https://example.com/contact?source=home", "final_url": "https://example.com/contact?source=home",
            "canonical": "https://example.com/contact", "status": 200, "text": repeated,
            "word_count": 135, "title": "Contact", "h1": ["Contact"], "h2": [],
        },
        {
            "url": "https://example.com/about", "final_url": "https://example.com/about",
            "canonical": "https://example.com/about", "status": 200,
            "text": " ".join(["verified company information"] * 45),
            "word_count": 135, "title": "About", "h1": ["About"], "h2": [],
        },
    ]
    global_scope.geolib.write_jsonl(evidence / "pages.jsonl", pages)
    global_scope.geolib.write_json(evidence / "site.json", {
        "root": "https://example.com", "pages_crawled": 3, "pages_ok": 3,
        "has_sitemap": True, "has_llms_txt": True, "ai_bots_blocked": [],
    })
    global_scope.geolib.write_json(project / "audit.json", {
        "market": "global", "page_count": 3,
        "pages": [{"url": page["url"], "score": 1} for page in pages],
    })
    monkeypatch.setattr(global_scope.geolib, "WORK", tmp_path)

    audit = global_scope.normalize_audit("example")

    normalized_pages = global_scope.geolib.read_jsonl(evidence / "pages.jsonl")
    site = global_scope.geolib.read_json(evidence / "site.json", {})
    assert audit["page_count"] == 2
    assert sum(audit["grade_distribution"].values()) == 2
    assert all(item["total"] == 2 for item in audit["block_gap"])
    assert audit["language_coverage"]["en_pages"] == 2
    scored_pages = [page for page in audit["pages"] if page["score"] is not None]
    assert len(scored_pages) == 1
    assert audit["avg_score"] == round(sum(page["score"] for page in scored_pages) / len(scored_pages), 1)
    assert site["pages_crawled"] == 2
    assert site["pages_ok"] == 2
    assert site["pages_crawled_raw"] == 3
    assert site["duplicate_pages_removed"] == 1
    assert normalized_pages[0]["url"] == "https://example.com/contact"
    assert normalized_pages[0]["duplicate_urls"] == ["https://example.com/contact?source=home"]


def test_profile_channels_preserve_engine_delivery_contract():
    required = {
        "kind", "forms", "volume", "cadence", "owner", "domains", "why", "effect",
        "coverage_status", "coverage_evidence",
    }
    engine_data = _engine_global_blueprint()

    for profile_id in global_scope.CHANNEL_STRATEGIES:
        profile = {"id": profile_id, "label": profile_id.title(), "confidence": "high", "evidence": []}
        blueprint = global_scope.normalize_blueprint_data(
            engine_data,
            profile=profile,
            cited_domains={"example.com", "docs.github.com", "g2.com", "youtube.com"},
            own_domain="example.com",
        )
        assert blueprint["channels"]
        for channel in blueprint["channels"]:
            assert required <= set(channel)
            assert isinstance(channel["forms"], list) and channel["forms"]
            assert isinstance(channel["domains"], list)
            assert not ({"fits", "national", "position", "platforms"} & set(channel))
        assert "# Example GEO Build Map" in delivery._build_map_markdown("Example", blueprint)


def test_profile_channel_defaults_override_engine_fields_and_are_isolated():
    profile = {"id": "publisher", "label": "Publisher", "confidence": "high", "evidence": []}
    first = global_scope.normalize_blueprint_data(
        _engine_global_blueprint(), profile=profile, cited_domains=set(), own_domain="example.com",
    )
    official = next(channel for channel in first["channels"] if channel["id"] == "official_en")

    assert official["forms"] == global_scope.CHANNEL_FIELD_DEFAULTS["official_en"]["forms"]
    assert official["forms"] != engine_blueprint.CHANNELS_GLOBAL[0]["forms"]
    official["forms"].append("Process-local mutation")
    official["domains"].append("mutated.example")

    second = global_scope.normalize_blueprint_data(
        _engine_global_blueprint(), profile=profile, cited_domains=set(), own_domain="example.com",
    )
    next_official = next(channel for channel in second["channels"] if channel["id"] == "official_en")
    assert "Process-local mutation" not in next_official["forms"]
    assert "Process-local mutation" not in global_scope.CHANNEL_FIELD_DEFAULTS["official_en"]["forms"]
    assert "mutated.example" not in global_scope.CHANNEL_FIELD_DEFAULTS["official_en"]["domains"]


def test_profile_channel_coverage_uses_citation_domains_and_marks_manual_channels():
    profile = {"id": "manufacturer", "label": "Manufacturer", "confidence": "high", "evidence": []}
    blueprint = global_scope.normalize_blueprint_data(
        _engine_global_blueprint(),
        profile=profile,
        cited_domains={"www.example.com", "supplier.alibaba.com", "youtube.com", "news.ycombinator.com"},
        own_domain="example.com",
    )
    channels = {channel["id"]: channel for channel in blueprint["channels"]}

    assert channels["official_en"]["coverage_status"] == "brand_cited"
    assert channels["b2b_marketplaces"]["coverage_status"] == "brand_cited"
    assert channels["b2b_marketplaces"]["coverage_evidence"] == ["supplier.alibaba.com"]
    assert channels["reddit"]["coverage_status"] == "brand_cited"
    assert channels["linkedin"]["coverage_status"] == "gap"
    assert channels["certification"]["coverage_status"] == "manual"
    assert channels["certification"]["covered"] is False
    assert blueprint["coverage"]["channel_manual"] == 3
    assert blueprint["coverage"]["channel_total"] == 6
    assert blueprint["coverage"]["channel_covered"] == 4

    markdown = delivery._build_map_markdown("Example", blueprint)
    assert "| Manual review | Requires confirmation against project-specific channels |" in markdown
    assert "Channels requiring manual confirmation: **3**" in markdown


def test_missing_citation_domains_preserve_existing_channel_coverage(tmp_path, monkeypatch):
    project = tmp_path / "example"
    metrics_path = project / "metrics" / "2026-08-14.json"
    metrics_path.parent.mkdir(parents=True)
    metrics_path.write_text(json.dumps({
        "platforms": {"openai": {"market": "global", "samples": 2}},
    }), "utf-8")
    monkeypatch.setattr(global_scope.geolib, "project_dir", lambda slug: project)

    channel_evidence = global_scope._latest_channel_evidence("example")
    assert channel_evidence is None
    blueprint = global_scope.normalize_blueprint_data(
        {
            "channels": [{
                "id": "official_en",
                "market": "global",
                "covered": True,
                "coverage_status": "covered",
                "coverage_evidence": ["example.com"],
            }],
        },
        profile={"id": "generic", "label": "General business", "confidence": "low", "evidence": []},
        cited_domains=None,
        observed_domains=None,
        own_domain="example.com",
    )
    official = next(channel for channel in blueprint["channels"] if channel["id"] == "official_en")
    assert official["coverage_status"] == "covered"
    assert official["coverage_evidence"] == ["example.com"]

    metrics_path.write_text(json.dumps({
        "platforms": {"openai": {"market": "global", "top_cited_domains": {}}},
    }), "utf-8")
    assert global_scope._latest_channel_evidence("example") == {"observed": set(), "brand": set()}


def test_project_normalization_updates_files(tmp_path, monkeypatch):
    project = tmp_path / "example"
    project.mkdir()
    (project / "geo.json").write_text(json.dumps({
        "market": "both",
        "brand": {"site": "https://example.com", "industry": "B2B SaaS software platform"},
        "questions": [{"id": "q001", "market": "cn", "text": "中文问题"}],
        "competitors": [],
        "platforms": ["deepseek", "openai"],
    }), "utf-8")
    (project / "metrics").mkdir()
    (project / "metrics" / "2026-08-13.json").write_text(json.dumps({
        "date": "2026-08-13",
        "question_count": 2,
        "sample_count": 3,
        "sample_summary": {"total": 3, "successful": 3, "failed": 0},
        "provenance": {
            "requested_platforms": ["deepseek", "openai"],
            "platforms": [
                {"engine_code": "deepseek"},
                {"engine_code": "openai"},
            ],
            "question_set": {"version": "legacy", "count": 2},
        },
        "platforms": {
            "deepseek": {"market": "cn", "samples": 1},
            "openai": {
                "market": "global", "samples": 2,
                "top_cited_domains": {"example.com": 2, "g2.com": 1, "github.com": 1},
                "top_brand_cited_domains": {"example.com": 2, "g2.com": 1},
            },
        },
    }), "utf-8")
    (project / "blueprint.json").write_text(json.dumps(_engine_global_blueprint()), "utf-8")
    monkeypatch.setattr(global_scope.geolib, "WORK", tmp_path)

    global_scope.normalize_project("example")

    config = json.loads((project / "geo.json").read_text("utf-8"))
    metrics = json.loads((project / "metrics" / "2026-08-13.json").read_text("utf-8"))
    blueprint = json.loads((project / "blueprint.json").read_text("utf-8"))
    assert config["questions"] == []
    assert config["platforms"] == ["openai"]
    assert list(metrics["platforms"]) == ["openai"]
    assert metrics["question_count"] == 0
    assert metrics["sample_count"] == 2
    assert metrics["sample_summary"]["successful"] == 2
    assert metrics["provenance"]["requested_platforms"] == ["openai"]
    assert metrics["provenance"]["platforms"] == [{"engine_code": "openai"}]
    assert metrics["provenance"]["question_set"]["count"] == 0
    channels = {channel["id"]: channel for channel in blueprint["channels"]}
    assert channels["official_en"]["coverage_status"] == "brand_cited"
    assert channels["review"]["coverage_status"] == "brand_cited"
    assert channels["developer_community"]["coverage_status"] == "observed_source"
    assert channels["docs"]["coverage_status"] == "manual"
    assert blueprint["coverage"]["channel_covered"] == 2
    assert blueprint["coverage"]["channel_observed"] == 1
