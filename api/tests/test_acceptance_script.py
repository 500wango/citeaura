from scripts.acceptance import collect_checks


class Response:
    def __init__(self, status_code=200, text="", body=None, headers=None):
        self.status_code = status_code
        self.text = text
        self._body = body or {}
        self.headers = headers or {}

    def json(self):
        return self._body


def test_acceptance_script_checks_public_surface(monkeypatch):
    html = "CiteAura API · Model knowledge API · Web-grounded retrieval Manual · Product surface /app"

    def fake_get(_url, timeout):
        if _url.endswith("/api/v1/health"):
            return Response(body={"status": "ok"})
        if _url.endswith("/llms.txt"):
            return Response(text="# CiteAura\nhttps://citeaura.com/docs")
        if _url.endswith("/about"):
            return Response(text="About CiteAura")
        if _url.endswith("/contact"):
            return Response(text="Contact CiteAura")
        return Response(text=html)

    monkeypatch.setattr("scripts.acceptance.requests.get", fake_get)
    result = collect_checks("http://example.test")

    assert result
    assert all(item["passed"] for item in result)


def test_acceptance_script_fails_when_llms_manifest_is_missing(monkeypatch):
    html = "CiteAura API · Model knowledge API · Web-grounded retrieval Manual · Product surface /app"

    def fake_get(_url, timeout):
        if _url.endswith("/api/v1/health"):
            return Response(body={"status": "ok"})
        if _url.endswith("/llms.txt"):
            return Response(status_code=404)
        if _url.endswith("/about"):
            return Response(text="About CiteAura")
        if _url.endswith("/contact"):
            return Response(text="Contact CiteAura")
        return Response(text=html)

    monkeypatch.setattr("scripts.acceptance.requests.get", fake_get)
    result = collect_checks("http://example.test")

    llms = next(item for item in result if item["name"] == "llms_manifest")
    assert llms == {"name": "llms_manifest", "passed": False, "detail": 404}


def test_acceptance_script_fails_when_server_is_unreachable(monkeypatch):
    def fail_get(_url, timeout):
        raise OSError("offline")

    monkeypatch.setattr("scripts.acceptance.requests.get", fail_get)
    result = collect_checks("http://example.test")

    assert result[-1] == {"name": "http", "passed": False, "detail": "OSError"}


def test_production_acceptance_requires_https_canonical_trailing_slash_redirect(monkeypatch):
    html = "CiteAura API · Model knowledge API · Web-grounded retrieval Manual · Product surface /app"

    def fake_get(url, timeout, **kwargs):
        if url.endswith("/docs/"):
            return Response(status_code=308, headers={"location": "https://example.test/docs"})
        if url.endswith("/api/v1/health"):
            return Response(body={"status": "ok"})
        if url.endswith("/api/v1/health/ready"):
            return Response(body={"status": "ready"})
        if url.endswith("/llms.txt"):
            return Response(text="# CiteAura\nhttps://citeaura.com/docs")
        if url.endswith("/about"):
            return Response(text="About CiteAura")
        if url.endswith("/contact"):
            return Response(text="Contact CiteAura")
        return Response(text=html)

    monkeypatch.setattr("scripts.acceptance.requests.get", fake_get)
    result = collect_checks("https://example.test", production=True)

    assert all(item["passed"] for item in result)
