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
            {"name": "Global Rival", "market": "global"},
            {"name": "Universal Rival", "market": "both"},
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
    unknown = global_scope.infer_business_profile({"brand": {"industry": ""}})

    assert manufacturer["id"] == "manufacturer"
    assert software["id"] == "software"
    assert service["id"] == "service"
    assert unknown == {
        "id": "generic", "label": "General business", "confidence": "low", "evidence": [],
    }

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

    assert channels["official_en"]["coverage_status"] == "covered"
    assert channels["b2b_marketplaces"]["coverage_status"] == "covered"
    assert channels["b2b_marketplaces"]["coverage_evidence"] == ["supplier.alibaba.com"]
    assert channels["reddit"]["coverage_status"] == "covered"
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

    cited_domains = global_scope._latest_cited_domains("example")
    assert cited_domains is None
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
        cited_domains=cited_domains,
        own_domain="example.com",
    )
    official = next(channel for channel in blueprint["channels"] if channel["id"] == "official_en")
    assert official["coverage_status"] == "covered"
    assert official["coverage_evidence"] == ["example.com"]

    metrics_path.write_text(json.dumps({
        "platforms": {"openai": {"market": "global", "top_cited_domains": {}}},
    }), "utf-8")
    assert global_scope._latest_cited_domains("example") == set()


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
    assert channels["official_en"]["coverage_status"] == "covered"
    assert channels["review"]["coverage_status"] == "covered"
    assert channels["developer_community"]["coverage_status"] == "covered"
    assert channels["docs"]["coverage_status"] == "manual"
    assert blueprint["coverage"]["channel_covered"] == 3
