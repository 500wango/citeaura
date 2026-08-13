from types import SimpleNamespace

from api.adapters import site_signals


def _response(text, content_type, *, status=200, url="https://example.com/resource"):
    return SimpleNamespace(
        text=text,
        content=text.encode(),
        status_code=status,
        url=url,
        headers={"Content-Type": content_type},
    )


def test_llms_validation_rejects_spa_fallback_and_accepts_facts_index():
    html = _response("<!doctype html><html><body><div id='app'></div></body></html>", "text/html")
    assert site_signals.validate_llms_response(html, "https://example.com")["reason"] == "html_fallback"

    facts = _response(
        "# Example\n\n> Example is a verified software platform for global teams.\n\n"
        "## Official pages\n\n- Website: https://example.com\n- Docs: https://example.com/docs\n",
        "text/plain; charset=utf-8",
        url="https://www.example.com/llms.txt",
    )
    result = site_signals.validate_llms_response(facts, "https://example.com")
    assert result["valid"] is True
    assert result["reason"] == "valid"


def test_sitemap_validation_requires_real_xml_with_locations():
    fallback = _response("<html><body>app</body></html>", "text/html")
    assert site_signals.validate_sitemap_response(fallback, "https://example.com")["reason"] == "html_fallback"

    invalid = _response("not xml", "application/xml")
    assert site_signals.validate_sitemap_response(invalid, "https://example.com")["reason"] == "invalid_xml"

    valid = _response(
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://example.com/</loc></url></urlset>",
        "application/xml",
        url="https://example.com/sitemap.xml",
    )
    result = site_signals.validate_sitemap_response(valid, "https://example.com")
    assert result["valid"] is True
    assert result["url_count"] == 1


def test_signal_validation_rejects_cross_site_redirect():
    response = _response(
        "# Example\n\n## Facts\n\n- One sufficiently detailed verified fact for the requested website.\n- Another fact.",
        "text/plain",
        url="https://unrelated.example/llms.txt",
    )
    assert site_signals.validate_llms_response(response, "https://example.com")["reason"] == "cross_site_redirect"


def test_project_validation_overrides_engine_false_positives(tmp_path, monkeypatch):
    project = tmp_path / "example"
    (project / "evidence").mkdir(parents=True)
    site_signals.geolib.write_json(project / "geo.json", {"brand": {"site": "https://example.com"}})
    site_signals.geolib.write_json(project / "evidence" / "site.json", {
        "root": "https://example.com", "has_llms_txt": True, "has_sitemap": True,
    })
    monkeypatch.setattr(site_signals.geolib, "project_dir", lambda _slug: project)
    monkeypatch.setattr(site_signals.geolib, "now_iso", lambda: "2026-08-14T00:00:00+00:00")
    results = iter((
        {"valid": False, "reason": "html_fallback", "status": 200},
        {"valid": False, "reason": "invalid_xml", "status": 200, "url_count": 0},
    ))
    monkeypatch.setattr(site_signals, "_fetch_result", lambda *args, **kwargs: next(results))

    site = site_signals.validate_project_signals("example")

    assert site["has_llms_txt"] is False
    assert site["has_sitemap"] is False
    assert site["signal_validation"]["llms_txt"]["reason"] == "html_fallback"


def test_fetch_rejects_private_targets_before_request(monkeypatch):
    requested = []
    monkeypatch.setattr(site_signals.requests, "get", lambda *args, **kwargs: requested.append(args[0]))

    result = site_signals._fetch_result(
        "http://127.0.0.1/llms.txt", "http://127.0.0.1", site_signals.validate_llms_response,
    )

    assert result["reason"] == "network_target_rejected"
    assert requested == []
