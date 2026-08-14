from api.adapters import brand_identity
from api.adapters import engine as engine_adapter
from api.adapters.engine import geolib, with_tenant_context


def test_category_terms_are_not_promoted_to_brand_aliases():
    config = brand_identity.normalize_config_identity({
        "brand": {
            "name": "CiteAura",
            "site": "https://citeaura.com",
            "aliases": ["GEO", "Generative Engine Optimization", "Cite Aura"],
            "industry": "Generative Engine Optimization (GEO) software",
            "products": ["AI visibility platform"],
        },
        "competitors": [],
    })

    assert config["brand"]["aliases"] == ["Cite Aura"]
    decisions = {item["value"]: item for item in config["brand"]["alias_review"]}
    assert decisions["GEO"]["reason"] == "category_or_product_term"
    assert decisions["Generative Engine Optimization"]["status"] == "rejected"
    assert decisions["Cite Aura"]["status"] == "active"


def test_identity_rules_are_industry_independent_and_evidence_driven():
    config = brand_identity.normalize_config_identity({
        "brand": {
            "name": "International Business Machines",
            "site": "https://ibm.com",
            "aliases": ["IBM", "Technology"],
            "industry": "Technology services",
            "products": [],
        },
        "competitors": [],
    })
    confirmed = brand_identity.normalize_config_identity({
        "brand": {
            "name": "Northstar Health",
            "aliases": ["NS Care"],
            "industry": "Healthcare services",
            "alias_evidence": [{
                "value": "NS Care", "status": "confirmed",
                "source_url": "https://northstar.example/about",
            }],
        },
        "competitors": [],
    })

    assert config["brand"]["aliases"] == ["IBM"]
    assert confirmed["brand"]["aliases"] == ["NS Care"]


def test_question_set_membership_does_not_assume_a_language():
    config = {
        "questions": [{"id": "q001", "text": "这个产品适合哪些团队？", "market": "global"}],
    }

    assert brand_identity.is_current_sample({
        "question_id": "q001",
        "question": "这个产品适合哪些团队？",
    }, config)


def test_reanalysis_preserves_raw_evidence_and_excludes_legacy_question_set(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    with with_tenant_context("tenant-a", "citeaura"):
        project = geolib.project_dir("citeaura")
        config = brand_identity.normalize_config_identity({
            "brand": {
                "name": "CiteAura",
                "site": "https://citeaura.com",
                "aliases": ["GEO", "Cite Aura"],
                "industry": "Generative Engine Optimization (GEO) software",
                "products": ["AI visibility platform"],
            },
            "questions": [{
                "id": "q101", "text": "Which GEO tools should an agency evaluate?", "market": "global",
            }],
            "competitors": [],
        })
        geolib.write_json(project / "geo.json", config)
        original_answer = "A dedicated GEO tool provides repeatable monitoring."
        geolib.write_jsonl(project / "samples" / "2026-08-13.jsonl", [
            {
                "question_id": "q101", "question": "Which GEO tools should an agency evaluate?",
                "market": "global", "platform": "openai", "ok": True,
                "answer": original_answer, "citations": [],
                "analysis": {"brand_mentioned": True, "brand_rank": 1, "candidates": ["CiteAura"]},
            },
            {
                "question_id": "q101", "question": "Which GEO tools should an agency evaluate?",
                "market": "global", "platform": "perplexity", "ok": True,
                "answer": "Cite Aura provides monitoring.", "citations": [],
                "analysis": {"brand_mentioned": False},
            },
            {
                "question_id": "q015", "question": "CiteAura 是做什么的？",
                "market": "global", "platform": "openai", "ok": True,
                "answer": "旧的中文原始证据", "citations": [],
                "analysis": {"brand_mentioned": True},
            },
        ])

        result = brand_identity.reanalyze_samples("citeaura", config)
        rows = geolib.read_jsonl(project / "samples" / "2026-08-13.jsonl")

    assert result == {"files": 1, "rows": 3, "changed": 3, "excluded": 1}
    assert rows[0]["answer"] == original_answer
    assert rows[0]["analysis"]["brand_mentioned"] is False
    assert rows[0]["analysis"]["matched_identity"] is None
    assert rows[1]["analysis"]["brand_mentioned"] is True
    assert rows[1]["analysis"]["matched_identity"]["text"] == "Cite Aura"
    assert rows[2]["answer"] == "旧的中文原始证据"
    assert rows[2]["included_in_metrics"] is False
    assert rows[2]["sample_exclusion_reason"] == "question_set_mismatch"
    assert rows[0]["analysis"]["analysis_version"] == brand_identity.ANALYSIS_VERSION
    assert len(rows[0]["analysis"]["identity_version"]) == 16
