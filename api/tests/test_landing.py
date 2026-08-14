from fastapi.testclient import TestClient

from api.main import app


client = TestClient(app)


def test_landing_page_is_public_and_links_to_application():
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<h1 id="hero-title" data-i18n="landing.hero_title">CiteAura</h1>' in response.text
    assert "CiteAura is a web-based Generative Engine Optimization (GEO) platform" in response.text
    assert "turn findings into trackable optimization work" in response.text
    assert "Google Search Console" not in response.text
    assert 'href="/app"' in response.text
    assert 'data-i18n="landing.mode_parametric"' in response.text
    assert 'data-i18n="landing.mode_search"' in response.text
    assert 'data-i18n="landing.mode_manual"' in response.text
    assert 'class="nav-sign-in"' in response.text
    assert 'href="/privacy"' in response.text
    assert 'href="/terms"' in response.text
    assert "$199" in response.text
    assert "$79" in response.text
    assert 'data-i18n="landing.pricing_note"' in response.text
    assert 'data-i18n="landing.ops_enterprise_dd"' in response.text


def test_public_verification_pages_support_head_requests():
    for path in ("/", "/privacy", "/terms", "/docs"):
        response = client.head(path)
        assert response.status_code == 200, path
        assert response.headers["content-type"].startswith("text/html"), path


def test_privacy_policy_has_no_removed_seo_integration_claims():
    response = client.get("/privacy")

    assert response.status_code == 200
    assert "Google Search Console" not in response.text
    assert "Semrush" not in response.text
    assert "TabAPI" not in response.text


def test_landing_assets_are_served():
    for path, content_type in (
        ("/site-assets/styles/tokens.css", "text/css"),
        ("/site-assets/styles/base.css", "text/css"),
        ("/site-assets/styles/components.css", "text/css"),
        ("/site-assets/styles/landing.css", "text/css"),
        ("/site-assets/landing.js", "text/javascript"),
        ("/site-assets/favicon.png", "image/png"),
        ("/site-assets/brand/mark.svg", "image/svg+xml"),
        ("/site-assets/fonts/space-grotesk-700.woff2", "font/woff2"),
        ("/site-assets/product-audit.webp", "image/webp"),
        ("/site-assets/product-plan.webp", "image/webp"),
        ("/site-assets/product-report.webp", "image/webp"),
        ("/site-assets/product-audit-en.webp", "image/webp"),
        ("/site-assets/product-plan-en.webp", "image/webp"),
        ("/site-assets/product-assets-en.webp", "image/webp"),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(content_type)


def test_i18n_catalogs_are_public():
    response = client.get("/i18n/en.json")
    assert response.status_code == 200
    data = response.json()
    assert data["nav.cta"] == "Start free trial"
    assert "landing.title" in data
    assert client.get("/i18n/zh.json").status_code == 404
    assert client.get("/i18n/ja.json").status_code == 404


def test_landing_has_no_forbidden_brand_or_false_claims():
    response = client.get("/")
    lowered = response.text.lower()

    assert "geolook" not in lowered
    assert "保证上首页" not in response.text
    assert "保证提及" not in response.text
    assert "已通过 SOC 2" not in response.text


def test_landing_js_is_english_only():
    response = client.get("/site-assets/landing.js")
    assert response.status_code == 200
    assert "localStorage.setItem('ulang'" in response.text
    assert "fetch('/i18n/en.json')" in response.text
    assert "zh-CN" not in response.text
    assert "ja" not in response.text


def test_seo_technical_files_are_served():
    robots_res = client.get("/robots.txt")
    assert robots_res.status_code == 200
    assert robots_res.headers["content-type"].startswith("text/plain")
    assert "User-agent: Googlebot" in robots_res.text
    assert "Sitemap: https://citeaura.com/sitemap.xml" in robots_res.text

    sitemap_res = client.get("/sitemap.xml")
    assert sitemap_res.status_code == 200
    assert "xml" in sitemap_res.headers["content-type"]
    assert "<loc>https://citeaura.com/</loc>" in sitemap_res.text
    assert "<loc>https://citeaura.com/docs</loc>" in sitemap_res.text
