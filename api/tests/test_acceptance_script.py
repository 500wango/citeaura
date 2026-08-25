from scripts.acceptance import collect_checks
from api.landing import PUBLIC_PAGES, SITE_BASE_URL
from urllib.parse import urlsplit


class Response:
    def __init__(self, status_code=200, text="", body=None, headers=None):
        self.status_code = status_code
        self.text = text
        self._body = body or {}
        self.headers = headers or {}

    def json(self):
        return self._body


def _public_html(url):
    path = urlsplit(url).path or "/"
    marker = "About CiteAura" if path == "/about" else "Contact CiteAura" if path == "/contact" else "CiteAura public page"
    return (
        "<!doctype html><html><head><title>CiteAura public page for SEO verification</title>"
        "<meta name=\"description\" content=\"CiteAura public documentation and evidence-based GEO workflow for brands, agencies, and technical teams.\">"
        "<meta name=\"robots\" content=\"index, follow\">"
        f"<link rel=\"canonical\" href=\"{SITE_BASE_URL}{path}\"></head>"
        f"<body><h1>{marker}</h1>API · Model knowledge API · Web-grounded retrieval Manual · Product surface</body></html>"
    )


def _sitemap():
    locs = "".join(f"<url><loc>{SITE_BASE_URL}{page['path']}</loc></url>" for page in PUBLIC_PAGES)
    return f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</urlset>'


def test_acceptance_script_checks_public_surface(monkeypatch):
    html = "CiteAura API · Model knowledge API · Web-grounded retrieval Manual · Product surface /app"

    def fake_get(_url, timeout):
        if _url.endswith("/api/v1/health"):
            return Response(body={"status": "ok"})
        if _url.endswith("/llms.txt"):
            return Response(text="# CiteAura\nhttps://citeaura.com/docs")
        if _url.endswith("/sitemap.xml"):
            return Response(text=_sitemap())
        if _url.endswith("/about"):
            return Response(text=_public_html(_url))
        if _url.endswith("/contact"):
            return Response(text=_public_html(_url))
        return Response(text=_public_html(_url))

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
        if _url.endswith("/sitemap.xml"):
            return Response(text=_sitemap())
        if _url.endswith("/about"):
            return Response(text=_public_html(_url))
        if _url.endswith("/contact"):
            return Response(text=_public_html(_url))
        return Response(text=_public_html(_url))

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
        if url.endswith("/sitemap.xml"):
            return Response(text=_sitemap())
        if url.endswith("/about"):
            return Response(text=_public_html(url))
        if url.endswith("/contact"):
            return Response(text=_public_html(url))
        return Response(text=_public_html(url))

    monkeypatch.setattr("scripts.acceptance.requests.get", fake_get)
    result = collect_checks("https://example.test", production=True)

    assert all(item["passed"] for item in result)
