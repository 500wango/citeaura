import json
from contextlib import nullcontext

from api.adapters import brand_facts, generated_assets


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", "utf-8")


def _seed_project(tmp_path, monkeypatch):
    project = tmp_path / "aqua.example"
    assets = project / "assets"
    (project / "content").mkdir(parents=True)
    (project / "evidence").mkdir()
    assets.mkdir()
    config = {
        "slug": "aqua-example",
        "market": "global",
        "brand": {
            "name": "AquaSense",
            "site": "https://aqua.example",
            "industry": "Industrial water-quality monitoring equipment",
            "products": ["Inline turbidity sensor", "Remote telemetry gateway"],
            "target_users": "Municipal and industrial water-treatment operators",
        },
        "questions": [{
            "id": "q101",
            "market": "global",
            "group": "recommendation",
            "text": "Which water-quality monitoring system fits a municipal treatment plant?",
        }],
        "competitors": [],
    }
    _write_json(project / "geo.json", config)
    _write_json(project / "audit.json", {
        "site": {"root": "https://aqua.example"},
        "pages": [{"url": "https://aqua.example", "title": "AquaSense", "score": 80}],
    })
    _write_json(project / "blueprint.json", {
        "contents": [{
            "id": "q101",
            "market": "global",
            "group": "recommendation",
            "question": config["questions"][0]["text"],
            "form": "Equipment selection guide",
        }],
    })
    (project / "evidence" / "pages.jsonl").write_text(
        json.dumps({
            "url": "https://aqua.example",
            "status": 200,
            "text": "AquaSense provides water-quality monitoring equipment for treatment teams.",
            "jsonld_types": ["Organization"],
        }) + "\n",
        "utf-8",
    )
    (project / "content" / "facts.md").write_text(
        "# AquaSense - Brand Fact Library\n\n"
        f"{brand_facts.REVIEWED_MARKER}\n\n"
        "## Entity\n\n"
        "| Field | Value | Evidence |\n"
        "|---|---|---|\n"
        "| Canonical name | AquaSense | A |\n"
        "| Official website | https://aqua.example | A |\n"
        "| Industry or category | Industrial water-quality monitoring equipment | A |\n\n"
        "## Definition\n\n"
        "> AquaSense provides water-quality monitoring equipment for municipal treatment teams.\n\n"
        "## Products and services\n\n"
        "- Inline turbidity sensor\n"
        "- Remote telemetry gateway\n\n"
        "## Audience and fit\n\n"
        "- Target audience: Municipal and industrial water-treatment operators\n"
        "- Business goal: Qualified equipment enquiries (inferred)\n\n"
        "**Good fit**\n\n- Continuous process-water monitoring\n\n"
        "**Not a fit**\n\n- Unverified medical diagnosis\n\n"
        "## Verified facts\n\n"
        "| Fact | Value | Source | Evidence |\n"
        "|---|---|---|---|\n"
        "| Sensor ingress rating | IP68 | Official specifications | A |\n",
        "utf-8",
    )

    chinese = "\u4e2d\u6587\u6a21\u677f"
    (assets / "llms.txt").write_text(f"# AquaSense\n\n> {chinese}\n", "utf-8")
    (assets / "llms.en.txt").write_text(f"# AquaSense\n\n> {chinese}\n", "utf-8")
    (assets / "snippets").mkdir()
    (assets / "snippets" / "definition.en.html").write_text(f"<!-- {chinese} -->", "utf-8")
    (assets / "snippets" / "faq.en.html").write_text(f"<!-- {chinese} -->", "utf-8")
    (assets / "snippets" / "definition.zh.html").write_text(f"<p>{chinese}</p>", "utf-8")
    (assets / "outlines").mkdir()
    (assets / "outlines" / "q101.md").write_text(f"# {chinese}\n", "utf-8")
    (assets / "outlines" / "q999.md").write_text(f"# {chinese}\n", "utf-8")
    _write_json(assets / "outlines" / "_index.json", {"summary": chinese})
    (assets / "drafts").mkdir()
    (assets / "drafts" / "q101.md").write_text(
        "<!-- \u521d\u7a3f\uff0c\u9700\u4eba\u5de5\u6838\u5b9e\u6240\u6709\u4e8b\u5b9e\u540e\u518d\u53d1\u5e03 \u00b7 2026-08-14 -->\n\n"
        "# AquaSense field guide\n",
        "utf-8",
    )
    (assets / "custom").mkdir()
    (assets / "custom" / "manual.txt").write_text("Keep this approved customer edit.\n", "utf-8")
    (assets / "custom" / "legacy.txt").write_text(chinese, "utf-8")
    _write_json(assets / "jsonld" / "organization.json", {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "AquaSense",
        "url": "https://aqua.example",
        "description": chinese,
    })
    _write_json(assets / "jsonld" / "faq-page.json", {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [{
            "@type": "Question",
            "name": "\u54ea\u4e2a\u7cfb\u7edf\u66f4\u9002\u5408\uff1f",
            "acceptedAnswer": {"@type": "Answer", "text": "\u5728\u8fd9\u91cc\u586b\u5199\u7b54\u6848"},
        }],
    })
    _write_json(assets / "jsonld" / "software-application.json", {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": "AquaSense",
        "url": "https://aqua.example",
        "description": chinese,
    })
    _write_json(assets / "index.json", {"assets": [f"assets/outlines/({chinese})"]})

    monkeypatch.setattr(generated_assets.geolib, "project_dir", lambda slug: project)
    monkeypatch.setattr(generated_assets.geolib, "project_lock", lambda slug: nullcontext())
    monkeypatch.setattr(generated_assets.geolib, "now_iso", lambda: "2026-08-14T12:00:00+00:00")
    return project, config


def test_generated_assets_migrate_to_project_aware_english_contract(tmp_path, monkeypatch):
    project, config = _seed_project(tmp_path, monkeypatch)

    state = generated_assets.normalize_project_assets("aqua-example", config=config)
    paths = {item["path"] for item in state["tree"]}

    assert "snippets/definition.zh.html" not in paths
    assert "outlines/q999.md" not in paths
    assert "custom/legacy.txt" not in paths
    assert "jsonld/software-application.json" not in paths
    assert "custom/manual.txt" in paths
    assert "drafts/q101.md" in paths
    assert "index.json" not in paths
    assert "outlines/_index.json" not in paths

    for relative in paths:
        text = (project / "assets" / relative).read_text("utf-8")
        assert not generated_assets.language_violation(relative)
        assert not generated_assets.language_violation(text)

    llms = (project / "assets" / "llms.en.txt").read_text("utf-8")
    assert "Industrial water-quality monitoring equipment" in llms
    assert "Inline turbidity sensor" in llms
    definition = (project / "assets" / "snippets" / "definition.en.html").read_text("utf-8")
    assert "AquaSense provides water-quality monitoring equipment" in definition
    assert "Sensor ingress rating" in definition
    organization = json.loads((project / "assets" / "jsonld" / "organization.json").read_text("utf-8"))
    assert organization["description"].startswith("AquaSense provides")
    faq = json.loads((project / "assets" / "jsonld" / "faq-page.json").read_text("utf-8"))
    assert faq["mainEntity"][0]["name"] == config["questions"][0]["text"]
    assert "Draft: verify every factual claim" in (project / "assets" / "drafts" / "q101.md").read_text("utf-8")
    assert (project / "assets" / "snippets" / "definition.zh.html").is_file()
    assert not generated_assets.language_violation((project / "assets" / "index.json").read_text("utf-8"))


def test_generated_assets_preserve_repeated_manual_english_edits(tmp_path, monkeypatch):
    project, config = _seed_project(tmp_path, monkeypatch)
    generated_assets.normalize_project_assets("aqua-example", config=config)
    outline = project / "assets" / "outlines" / "q101.md"
    outline.write_text("# Customer-approved equipment outline\n", "utf-8")
    generated_assets.mark_manual_edit("aqua-example", "outlines/q101.md")

    with generated_assets.preserve_manual_asset_edits("aqua-example"):
        outline.write_text("# \u4e2d\u6587\u6a21\u677f\n", "utf-8")

    generated_assets.normalize_project_assets("aqua-example", config=config)

    assert outline.read_text("utf-8") == "# Customer-approved equipment outline\n"
    assert (project / "assets" / "custom" / "manual.txt").read_text("utf-8") == (
        "Keep this approved customer edit.\n"
    )
    assert ".citeaura-manual-edits.json" not in {item["path"] for item in (
        generated_assets.normalize_project_assets("aqua-example", config=config)["tree"]
    )}


def test_asset_validation_rejects_encoded_chinese_and_internal_paths():
    for value in (
        "\u4e2d\u6587",
        r"\u4e2d\u6587",
        r"\U00020000",
        r"\ud840\udc00",
        "\ud800",
        "&#20013;&#25991;",
        "English\u3002",
    ):
        try:
            generated_assets.validate_asset_text(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected language violation for {value!r}")

    for value in ("../geo.json", "/etc/passwd", "snippets/definition.zh.html", "index.json"):
        try:
            generated_assets.validate_asset_path(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected invalid asset path for {value!r}")
