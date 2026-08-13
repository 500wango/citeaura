from api.adapters import engine as engine_adapter
from api.adapters import framing
from api.adapters.engine import geolib, with_tenant_context


def _row(answer, platform, platform_name, market="global", **extra):
    return {
        "question_id": f"q-{platform}",
        "question": "How is the brand described?",
        "answer": answer,
        "platform": platform,
        "platform_name": platform_name,
        "market": market,
        "analysis": {"brand_mentioned": True},
        **extra,
    }


def test_framing_uses_latest_samples_and_keeps_source_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    with with_tenant_context("tenant-a", "example"):
        project_dir = geolib.project_dir("example")
        geolib.write_json(
            project_dir / "geo.json",
            {
                "slug": "example",
                "market": "both",
                "brand": {
                    "name": "CiteAura",
                    "aliases": ["Cite Aura"],
                    "site": "https://example.com",
                },
            },
        )
        geolib.write_jsonl(
            project_dir / "samples" / "2026-07-30.jsonl",
            [_row("CiteAura is an old product.", "openai", "OpenAI")],
        )
        geolib.write_jsonl(
            project_dir / "samples" / "2026-07-31.jsonl",
            [
                _row(
                    "CiteAura is described as a reliable GEO analysis tool for marketing teams.",
                    "openai",
                    "OpenAI",
                    sample_mode="api",
                    search_enabled=False,
                ),
                _row(
                    "Analysts say Cite Aura is described as a reliable GEO analysis tool for marketing teams.",
                    "perplexity",
                    "Perplexity",
                    sample_mode="api",
                    search_enabled=True,
                ),
                _row(
                    "CiteAura 是一款专业的 AI 可见性分析平台，适合品牌团队。",
                    "chatgpt",
                    "ChatGPT 网页版",
                    market="cn",
                    sample_mode="manual",
                    terminal="web",
                ),
                {
                    **_row("The answer does not mention it.", "gemini", "Gemini"),
                    "analysis": {"brand_mentioned": False},
                },
            ],
        )

        result = framing.build("example")

    assert result["status"] == "ready"
    assert result["date"] == "2026-07-31"
    assert result["sample_count"] == 3
    assert result["mentioned_samples"] == 2
    assert [item["term"] for item in result["terms"]] == [
        "reliable GEO analysis tool for marketing teams",
    ]
    repeated = result["terms"][0]
    assert repeated["count"] == 2
    assert repeated["share"] == 1.0
    assert repeated["engines"] == ["OpenAI", "Perplexity"]
    assert {item["sampling_mode"] for item in repeated["evidence"]} == {"API - Parametric knowledge", "API - Search grounded"}
    assert "专业的 AI" not in str(result)
    assert "old product" not in str(result)


def test_framing_returns_explicit_empty_states(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    with with_tenant_context("tenant-a", "empty"):
        project_dir = geolib.project_dir("empty")
        geolib.write_json(
            project_dir / "geo.json",
            {
                "slug": "empty",
                "market": "global",
                "brand": {"name": "CiteAura", "site": "https://example.com"},
            },
        )
        assert framing.build("empty")["status"] == "no_samples"

        geolib.write_jsonl(
            project_dir / "samples" / "2026-07-31.jsonl",
            [{**_row("No matching brand.", "openai", "OpenAI"), "analysis": {"brand_mentioned": False}}],
        )
        assert framing.build("empty")["status"] == "brand_not_mentioned"

        geolib.write_jsonl(
            project_dir / "samples" / "2026-08-01.jsonl",
            [_row("CiteAura appears in this answer without a descriptor.", "openai", "OpenAI")],
        )
        assert framing.build("empty")["status"] == "no_descriptors"
