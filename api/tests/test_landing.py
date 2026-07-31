from fastapi.testclient import TestClient

from api.main import app


client = TestClient(app)


def test_landing_page_is_public_and_links_to_application():
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<h1 id=\"hero-title\">DisvorAI</h1>" in response.text
    assert 'href="/app"' in response.text
    assert "API·参数化知识" in response.text
    assert "API·联网检索" in response.text
    assert "人工·产品端" in response.text
    assert "14 天" in response.text
    assert "¥199" in response.text
    assert "不保证被提及或排名" in response.text
    assert "未获得 SOC 2 认证" in response.text


def test_landing_assets_are_served():
    for path, content_type in (
        ("/site-assets/styles.css", "text/css"),
        ("/site-assets/landing.js", "text/javascript"),
        ("/site-assets/favicon.png", "image/png"),
        ("/site-assets/product-audit.webp", "image/webp"),
        ("/site-assets/product-plan.webp", "image/webp"),
        ("/site-assets/product-report.webp", "image/webp"),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(content_type)


def test_landing_has_no_forbidden_brand_or_false_claims():
    response = client.get("/")
    lowered = response.text.lower()

    assert "geolook" not in lowered
    assert "保证上首页" not in response.text
    assert "保证提及" not in response.text
    assert "已通过 SOC 2" not in response.text
