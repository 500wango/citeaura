from fastapi.testclient import TestClient

from api.main import app


client = TestClient(app)


def test_landing_page_is_public_and_links_to_application():
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="hero-title" data-i18n="landing.hero_title"' in response.text
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
    for locale, sample in (
        ("en", "Start free trial"),
        ("zh", "免费试用"),
        ("ja", "無料トライアル"),
    ):
        response = client.get(f"/i18n/{locale}.json")
        assert response.status_code == 200
        data = response.json()
        assert data["nav.cta"] == sample
        assert "landing.title" in data


def test_landing_has_no_forbidden_brand_or_false_claims():
    response = client.get("/")
    lowered = response.text.lower()

    assert "geolook" not in lowered
    assert "保证上首页" not in response.text
    assert "保证提及" not in response.text
    assert "已通过 SOC 2" not in response.text


def test_landing_js_uses_shared_locale_preference():
    response = client.get("/site-assets/landing.js")
    assert response.status_code == 200
    assert "localStorage.getItem('ulang')" in response.text
    assert "localStorage.setItem('ulang'" in response.text
    assert "fetch('/i18n/' + state.locale + '.json')" in response.text
    assert 'data-locale-src-' in response.text
