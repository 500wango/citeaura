import pytest
from api.projects.reporting import product_report

def test_product_report_includes_sample_count_and_grade(monkeypatch):
    import api.projects.reporting as reporting
    from api.adapters.engine import geolib
    
    monkeypatch.setattr(geolib, "project_dir", lambda slug: geolib.Path("/tmp"))
    monkeypatch.setattr(geolib, "load_config", lambda slug: {"brand": {"name": "Test"}})
    
    monkeypatch.setattr(reporting, "current_sample_rows", lambda slug, config: (None, []))
    
    class DummyAnalytics:
        @staticmethod
        def engines(slug, rows, metrics):
            return [{"platform": "openai", "mention": 0.5, "samples": 100}]
            
    import sys
    sys.modules["analytics"] = DummyAnalytics()
    
    from api.adapters import audit_presentation
    monkeypatch.setattr(audit_presentation, "present_audit", lambda slug: {
        "applicable_grade": None,
        "avg_score": 80
    })
    
    from api.adapters import product_insights
    monkeypatch.setattr(product_insights, "build", lambda *a, **kw: {})
    
    report = reporting.product_report("test-project", {})
    assert report["sample_count"] == 100
    assert report["grade"] is None
