import pytest
from api.adapters.delivery_documents import _audit_markdown
from api.adapters.engine import geolib

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
