import json

from api.adapters import global_scope


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
        "channel_total": 4,
        "channel_covered": 1,
        "channel_rate": 0.25,
        "p0p1_total": 4,
        "p0p1_covered": 1,
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


def test_project_normalization_updates_files(tmp_path, monkeypatch):
    project = tmp_path / "example"
    project.mkdir()
    (project / "geo.json").write_text(json.dumps({
        "market": "both",
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
            "openai": {"market": "global", "samples": 2},
        },
    }), "utf-8")
    monkeypatch.setattr(global_scope.geolib, "WORK", tmp_path)

    global_scope.normalize_project("example")

    config = json.loads((project / "geo.json").read_text("utf-8"))
    metrics = json.loads((project / "metrics" / "2026-08-13.json").read_text("utf-8"))
    assert config["questions"] == []
    assert config["platforms"] == ["openai"]
    assert list(metrics["platforms"]) == ["openai"]
    assert metrics["question_count"] == 0
    assert metrics["sample_count"] == 2
    assert metrics["sample_summary"]["successful"] == 2
    assert metrics["provenance"]["requested_platforms"] == ["openai"]
    assert metrics["provenance"]["platforms"] == [{"engine_code": "openai"}]
    assert metrics["provenance"]["question_set"]["count"] == 0
