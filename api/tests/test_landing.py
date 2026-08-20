import re

from fastapi.testclient import TestClient

from api.main import app


client = TestClient(app)


def test_landing_page_is_public_and_links_to_application():
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="hero-title" data-i18n="landing.hero_title"' in response.text
    assert "Win brand visibility in the" in response.text
    assert "AI search era" in response.text
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
    assert "Scheduled re-sampling and email alerts on mention-rate drops" in response.text
    assert "One-click sendable white-label client pack" in response.text
    assert "6 BYOK engines + custom" in response.text
    assert "5 BYOK engines + custom" not in response.text
    assert "model-ribbon-name\">DeepSeek</span>" in response.text
    assert "data-radar-bar=\"grok\"" in response.text
    assert 'data-i18n="landing.ops_enterprise_dd"' in response.text
    assert "CiteAura is a Generative Engine Optimization platform that audits, measures, and improves brand citations" in response.text
    assert "id=\"about\"" in response.text
    assert "CiteAura versus traditional SEO tools" in response.text
    assert "Step 1." in response.text
    assert "14 days" in response.text
    assert "Updated 2026-08-19" in response.text


def test_public_verification_pages_support_head_requests():
    for path in (
        "/",
        "/privacy",
        "/terms",
        "/docs",
        "/blog",
        "/blog/measure-if-chatgpt-mentions-your-brand",
        "/blog/why-chatgpt-does-not-mention-my-brand",
        "/blog/gptbot-blocked-by-robots-txt",
        "/blog/what-to-put-in-llms-txt",
        "/blog/white-label-geo-diagnostic-report",
    ):
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
        ("/site-assets/styles/blog.css", "text/css"),
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

    blog_css = client.get("/site-assets/styles/blog.css")
    assert ".blog-article a:not(.btn)" in blog_css.text
    assert ".blog-article a {" not in blog_css.text


def test_i18n_catalogs_are_public():
    response = client.get("/i18n/en.json")
    assert response.status_code == 200
    data = response.json()
    assert data["nav.cta"] == "Start free trial"
    assert data["landing.plan_pro_3"] == "Scheduled re-sampling and email alerts on mention-rate drops"
    assert data["landing.plan_agency_2"] == "One-click sendable white-label client pack"
    assert data["nav.status"] == "6 BYOK engines + custom"
    assert "DeepSeek" in data["landing.truth_engines_dd"]
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
    assert "initTypewriter()" in response.text
    assert "Audit citations across 6 BYOK engines plus custom endpoints." in response.text
    assert "fetch('/i18n/en.json')" in response.text
    assert "zh-CN" not in response.text
    assert "ja" not in response.text


def test_seo_technical_files_are_served():
    robots_res = client.get("/robots.txt")
    assert robots_res.status_code == 200
    assert robots_res.headers["content-type"].startswith("text/plain")
    assert "User-agent: Googlebot" in robots_res.text
    assert "Sitemap: https://citeaura.com/sitemap.xml" in robots_res.text
    assert "Allow: /blog" in robots_res.text
    assert "User-agent: GPTBot" in robots_res.text
    assert "User-agent: ClaudeBot" in robots_res.text
    assert "User-agent: Google-Extended" in robots_res.text

    sitemap_res = client.get("/sitemap.xml")
    assert sitemap_res.status_code == 200
    assert "xml" in sitemap_res.headers["content-type"]
    assert "<loc>https://citeaura.com/</loc>" in sitemap_res.text
    assert "<loc>https://citeaura.com/docs</loc>" in sitemap_res.text
    assert "<loc>https://citeaura.com/blog</loc>" in sitemap_res.text
    assert "<loc>https://citeaura.com/blog/measure-if-chatgpt-mentions-your-brand</loc>" in sitemap_res.text
    assert "<loc>https://citeaura.com/blog/why-chatgpt-does-not-mention-my-brand</loc>" in sitemap_res.text
    assert "<loc>https://citeaura.com/blog/gptbot-blocked-by-robots-txt</loc>" in sitemap_res.text
    assert "<loc>https://citeaura.com/blog/what-to-put-in-llms-txt</loc>" in sitemap_res.text
    assert "<loc>https://citeaura.com/blog/white-label-geo-diagnostic-report</loc>" in sitemap_res.text

    llms_res = client.get("/llms.txt")
    assert llms_res.status_code == 200
    assert llms_res.headers["content-type"].startswith("text/plain")
    assert llms_res.text.startswith("# CiteAura\n")
    assert "https://citeaura.com/docs" in llms_res.text
    assert "https://citeaura.com/blog" in llms_res.text
    assert "https://citeaura.com/app/" not in llms_res.text
    assert "API - Parametric knowledge" in llms_res.text
    assert "CiteAura is a Generative Engine Optimization platform that audits, measures, and improves brand citations" in llms_res.text
    assert "14 days" in llms_res.text
    assert client.head("/llms.txt").status_code == 200


def test_blog_index_and_articles_are_static_html():
    index = client.get("/blog")
    assert index.status_code == 200
    assert index.headers["content-type"].startswith("text/html")
    assert "<h1>Measure and diagnose AI brand visibility</h1>" in index.text
    assert 'href="/blog/measure-if-chatgpt-mentions-your-brand"' in index.text
    assert 'href="/blog/why-chatgpt-does-not-mention-my-brand"' in index.text
    assert 'href="/blog/gptbot-blocked-by-robots-txt"' in index.text
    assert 'href="/blog/what-to-put-in-llms-txt"' in index.text
    assert 'href="/blog/white-label-geo-diagnostic-report"' in index.text
    assert 'rel="canonical" href="https://citeaura.com/blog"' in index.text

    articles = (
        (
            "/blog/measure-if-chatgpt-mentions-your-brand",
            "How to Measure ChatGPT Brand Mentions",
            "API · Model knowledge",
        ),
        (
            "/blog/why-chatgpt-does-not-mention-my-brand",
            "Why ChatGPT Does Not Mention Your Brand",
            "API · Web-grounded retrieval",
        ),
        (
            "/blog/gptbot-blocked-by-robots-txt",
            "GPTBot Blocked by robots.txt? Find and Fix the Rule",
            "User-agent: GPTBot",
        ),
        (
            "/blog/what-to-put-in-llms-txt",
            "What to Put in llms.txt for Your Brand",
            "text/plain",
        ),
        (
            "/blog/white-label-geo-diagnostic-report",
            "White-Label GEO Diagnostic Reports for Agencies",
            "API · Model knowledge",
        ),
    )
    for path, headline, marker in articles:
        page = client.get(path)
        assert page.status_code == 200, path
        assert f"<h1>{headline}</h1>" in page.text
        assert marker in page.text
        assert "does not guarantee" in page.text
        assert f'rel="canonical" href="https://citeaura.com{path}"' in page.text
        assert page.text.count('href="https://') >= 3
        assert "<h2>Sources</h2>" in page.text
        assert page.text.count("<h1") == 1
        assert '"@type": "FAQPage"' in page.text
        assert 'class="blog-related"' in page.text
        assert 'class="blog-cta"' in page.text
        assert 'class="btn btn-primary" href="/app?auth=register">Start free trial</a>' in page.text
        title = re.search(r"<title>([^<]+)</title>", page.text)
        assert title is not None
        assert 55 <= len(title.group(1)) <= 70

    assert client.get("/blog/not-a-real-slug").status_code == 404


def test_homepage_keeps_slogan_h1_and_links_guides():
    response = client.get("/")
    assert 'id="hero-title" data-i18n="landing.hero_title"' in response.text
    assert "Win brand visibility in the" in response.text
    assert 'id="primary-nav"' in response.text
    assert 'href="/blog" data-i18n="nav.guides">Guides</a>' in response.text
    assert 'class="header-status-badge"' not in response.text
    assert 'class="hero-status-badge"' in response.text
    assert 'data-i18n="nav.status"' in response.text
    assert 'id="blog"' in response.text
    assert 'href="/blog/measure-if-chatgpt-mentions-your-brand"' in response.text
    assert 'href="/blog/why-chatgpt-does-not-mention-my-brand"' in response.text
    assert 'href="/blog/gptbot-blocked-by-robots-txt"' in response.text
    assert 'href="/blog/what-to-put-in-llms-txt"' in response.text
    assert 'href="/blog/white-label-geo-diagnostic-report"' in response.text
