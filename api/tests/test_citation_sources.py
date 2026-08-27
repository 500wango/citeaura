import json
import os
import time
import pytest

from api.adapters import citation_sources, offsite_entities
from api.adapters.engine import geolib
from api.projects.citation_source_routes import CitationTicketPayload, _ensure_citation_ticket


def _write_run(tmp_path, rows, name="sample-run-1.jsonl"):
    project = tmp_path / "demo"
    samples = project / "samples"
    samples.mkdir(parents=True)
    path = samples / name
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", "utf-8")
    old = time.time() - 3
    os.utime(path, (old, old))
    return project


def test_citation_aggregate_measured_is_stable_and_deduplicated(tmp_path):
    _write_run(tmp_path, [{"ok": True, "search_enabled": True, "citations": ["https://www.reddit.com/a", "https://reddit.com/a", "https://example.com/x"], "analysis": {"cited_domains": ["reddit.com", "example.com"]}}])
    with geolib.scoped_paths(tmp_path, tmp_path):
        first = citation_sources.aggregate("demo")
        second = citation_sources.aggregate("demo")
    assert first == second
    assert first["status"] == "measured"
    assert first["total_citations"] == 2
    assert [item["domain"] for item in first["domains"]] == ["example.com", "reddit.com"]
    assert first["domains"][1]["type"] == "community"
    assert "shadow_mismatch" not in first["warnings"]


def test_citation_aggregate_skips_bad_lines_and_unmeasured_parametric(tmp_path):
    project = _write_run(tmp_path, [{"ok": True, "search_enabled": False, "citations": ["https://example.com/a"]}])
    path = next((project / "samples").glob("*.jsonl"))
    path.write_text(path.read_text("utf-8") + "{bad\n", "utf-8")
    old = time.time() - 3; os.utime(path, (old, old))
    with geolib.scoped_paths(tmp_path, tmp_path): result = citation_sources.aggregate("demo")
    assert result["status"] == "unmeasured"
    assert result["unmeasured_reason"] == "no_valid_citations"
    assert result["warnings"]


def test_entities_empty_save_prevents_repopulation_and_tombstone_restores(tmp_path):
    (tmp_path / "demo").mkdir()
    with geolib.scoped_paths(tmp_path, tmp_path):
        initial = offsite_entities.load("demo", ["example.com"])
        offsite_entities.save("demo", initial)
        offsite_entities.save("demo", [item for item in initial if not item["id"].startswith("domain_")])
        saved = offsite_entities.load("demo", ["example.com"])
        dynamic_id = next(item["id"] for item in initial if item["id"].startswith("domain_"))
        assert all(item["id"] != dynamic_id for item in saved)
        assert offsite_entities.restore("demo", dynamic_id) is True
        assert any(item["id"] == dynamic_id for item in offsite_entities.load("demo"))
        assert offsite_entities.restore("demo", dynamic_id) is False


def test_citation_ticket_is_idempotent_and_keeps_evidence(tmp_path):
    (tmp_path / "demo").mkdir()
    payload = CitationTicketPayload(domain="example.com", run_id="sample-run-1", suggested_asset="FAQ", evidence_urls=["https://example.com/evidence"])
    with geolib.scoped_paths(tmp_path, tmp_path):
        first, reused_first = _ensure_citation_ticket("demo", payload)
        second, reused_second = _ensure_citation_ticket("demo", payload)
    assert reused_first is False and reused_second is True
    assert first == second
    assert first["run_id"] == "sample-run-1"
    assert first["evidence"][0]["url"] == "https://example.com/evidence"


def test_entity_urls_reject_private_targets_and_fixed_identity_changes(tmp_path):
    (tmp_path / "demo").mkdir()
    with geolib.scoped_paths(tmp_path, tmp_path):
        with pytest.raises(ValueError, match="private entity URL"):
            offsite_entities.save("demo", [{"id": "custom", "platform": "custom", "source": "custom", "url": "http://127.0.0.1/a", "status": "pending"}])
        with pytest.raises(ValueError, match="invalid fixed entity"):
            offsite_entities.save("demo", [{"id": "official_site", "platform": "LinkedIn", "source": "fixed", "url": "", "status": "pending"}])
