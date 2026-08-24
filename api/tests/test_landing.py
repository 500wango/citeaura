import re
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app


client = TestClient(app)


def test_landing_page_is_public_and_links_to_application():
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="hero-title" data-i18n="landing.hero_title"' in response.text
    assert "Find out why AI overlooks your brand" in response.text
    assert "AI answer → citation gap → page change → acceptance check → re-test" in response.text
    assert "Mention Rate" in response.text
    assert "Citation Rate" in response.text
    assert "View a sample report" in response.text
    assert 'href="/sample-report"' in response.text
    assert "AI search era" in response.text
    assert "Google Search Console" not in response.text
    assert 'href="/app"' in response.text
    assert 'data-i18n="landing.mode_parametric"' in response.text
    assert 'data-i18n="landing.mode_search"' in response.text
    assert 'data-i18n="landing.mode_manual"' in response.text
    assert 'class="nav-sign-in"' in response.text
    assert '<a href="#simulator" data-i18n="nav.simulator">Free AI Audit</a>' not in response.text
    assert '<a href="#about" data-i18n="public.nav.what_it_is">Overview</a>' in response.text
    assert '<a href="#product" data-i18n="nav.product">Features</a>' in response.text
    assert '<a href="#tickets" data-i18n="nav.tickets">Action Tickets</a>' not in response.text
    assert 'href="/privacy"' in response.text
    assert 'href="/terms"' in response.text
    assert 'href="/about"' in response.text
    assert 'href="/contact"' in response.text
    assert "$199" in response.text
    assert "$79" in response.text
    assert 'data-i18n="landing.pricing_note"' in response.text
    assert "Scheduled re-sampling and email alerts on mention-rate drops" in response.text
    assert "One-click sendable white-label client pack" in response.text
    assert "6 API engines + 9 product surfaces + custom" in response.text
    assert "5 BYOK engines + custom" not in response.text
    assert "model-ribbon-name\">DeepSeek</span>" in response.text
    assert "data-radar-bar=\"grok\"" in response.text
    assert 'data-i18n="landing.ops_enterprise_dd"' in response.text
    assert "CiteAura is a Generative Engine Optimization platform that audits, measures, and improves brand citations" in response.text
    assert "id=\"about\"" in response.text
    assert "CiteAura versus traditional SEO tools" in response.text
    assert "Step 1." in response.text
    assert 'data-i18n="landing.howto_title"' in response.text
    assert 'data-i18n="landing.howto_1_body"' in response.text
    assert 'data-i18n="landing.compare_rarely_published"' in response.text
    assert "14 days" in response.text
    assert "Updated 2026-08-19" in response.text
    assert "Sources and definitions:" in response.text
    

def test_public_verification_pages_support_head_requests():
    for path in (
        "/",
        "/about",
        "/contact",
        "/privacy",
        "/terms",
        "/docs",
        "/sample-report",
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

    sample = client.get("/sample-report")
    assert sample.status_code == 200
    assert "Example diagnostic pack" in sample.text
    assert "all domain names, prompts, rates, and ticket outcomes" in sample.text


def test_public_navigation_does_not_duplicate_hero_audit_cta():
    paths = (
        "/",
        "/docs",
        "/blog",
        "/blog/measure-if-chatgpt-mentions-your-brand",
        "/blog/why-chatgpt-does-not-mention-my-brand",
        "/blog/gptbot-blocked-by-robots-txt",
        "/blog/what-to-put-in-llms-txt",
        "/blog/white-label-geo-diagnostic-report",
    )
    nav_link = 'data-i18n="nav.simulator">Free AI Audit</a>'
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, path
        assert nav_link not in response.text, path

    landing = client.get("/")
    assert 'href="#simulator" data-i18n="landing.final_secondary"' in landing.text


def test_about_and_contact_pages_expose_provenance_and_real_support_channel():
    about = client.get("/about")
    assert about.status_code == 200
    assert '<h1 data-i18n="public.about.h1">GEO diagnosis with evidence boundaries</h1>' in about.text
    canonical_definition = (
        "CiteAura is a Generative Engine Optimization platform that audits, measures, and improves "
        "brand citations, mentions, and visibility in generative AI engines, then closes the loop "
        "with engineering tickets and verification."
    )
    assert canonical_definition in about.text
    assert '"description": "' + canonical_definition in about.text
    assert '"@type": "AboutPage"' in about.text
    assert "does not guarantee a mention, ranking, or citation" in about.text
    assert "OpenAI crawler documentation" in about.text

    contact = client.get("/contact")
    assert contact.status_code == 200
    assert '<h1 data-i18n="public.contact.h1">Choose the right support channel</h1>' in contact.text
    assert '"@type": "ContactPage"' in contact.text
    assert 'mailto:privacy@citeaura.com' in contact.text
    assert "do not send passwords" in contact.text

    docs = client.get("/docs")
    assert docs.status_code == 200
    assert 'href="/#tickets"' not in docs.text
    assert '"author": {' in docs.text
    assert "Maintained by CiteAura Editorial Team" in docs.text


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
        ("/site-assets/product-audit-clay.webp", "image/webp"),
        ("/site-assets/product-plan-clay.webp", "image/webp"),
        ("/site-assets/product-assets-clay.webp", "image/webp"),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(content_type)

    blog_css = client.get("/site-assets/styles/blog.css")
    assert ".blog-article a:not(.btn)" in blog_css.text
    assert ".blog-article a {" not in blog_css.text


def test_product_gallery_uses_current_clay_visual_assets():
    response = client.get("/")
    assert 'src="/site-assets/product-audit-clay.webp"' in response.text
    assert 'src="/site-assets/product-plan-clay.webp"' in response.text
    assert 'src="/site-assets/product-assets-clay.webp"' in response.text
    assert 'src="/site-assets/product-audit-en.webp"' not in response.text
    assert 'src="/site-assets/product-plan-en.webp"' not in response.text
    assert 'src="/site-assets/product-assets-en.webp"' not in response.text


def test_i18n_catalogs_are_public():
    response = client.get("/i18n/en.json")
    assert response.status_code == 200
    data = response.json()
    assert data["nav.cta"] == "Start free trial"
    assert data["landing.plan_pro_3"] == "Scheduled re-sampling and email alerts on mention-rate drops"
    assert data["landing.plan_agency_2"] == "One-click sendable white-label client pack"
    assert data["nav.status"] == "6 API engines + 9 product surfaces + custom"
    assert "DeepSeek" in data["landing.truth_engines_dd"]
    assert "landing.title" in data
    assert client.get("/i18n/zh.json").status_code == 200
    assert client.get("/i18n/ja.json").status_code == 200
    assert client.get("/i18n/de.json").status_code == 200


def test_public_zh_catalog_covers_docs_and_guides():
    response = client.get("/i18n/public/zh.json")
    assert response.status_code == 200
    catalog = response.json()
    assert catalog["public.meta.docs_title"].startswith("CiteAura 文档")
    assert catalog["public.g2.sec1_h2"] == "ChatGPT 跳过品牌的常见原因"

    root = Path(__file__).resolve().parents[2] / "web"
    pages = [root / "docs.html", root / "blog" / "index.html", *sorted((root / "blog").glob("*.html"))]
    for page in pages:
        keys = set(re.findall(r'data-i18n(?:-[a-z]+)*="([^"]+)"', page.read_text("utf-8")))
        missing = sorted(key for key in keys if key.startswith("public.") and key not in catalog)
        assert not missing, (page, missing)

    assert "public.g2.sec1_h2" in (root / "blog" / "why-chatgpt-does-not-mention-my-brand.html").read_text("utf-8")
    assert "public.docs.admin_brand_use" in (root / "docs.html").read_text("utf-8")
    assert client.get("/i18n/public/en.json").status_code == 404


def test_public_zh_catalog_covers_all_localized_public_pages():
    catalog = client.get("/i18n/public/zh.json").json()
    root = Path(__file__).resolve().parents[2] / "web"
    pages = [
        root / "index.html",
        root / "about.html",
        root / "contact.html",
        root / "privacy.html",
        root / "terms.html",
        root / "sample-report.html",
    ]
    for page in pages:
        keys = set(re.findall(r'data-i18n(?:-[a-z]+)*="([^\"]+)"', page.read_text("utf-8")))
        missing = sorted(key for key in keys if key.startswith("public.") and key not in catalog)
        assert not missing, (page, missing)


def test_public_zh_docs_does_not_retain_english_action_labels():
    """Chinese Docs copy must not expose provider-console UI labels in English prose."""
    catalog = client.get("/i18n/public/zh.json").json()
    product_catalog = client.get("/i18n/zh.json").json()
    forbidden = (
        "Create new secret key",
        "Create Key",
        "Create API key",
        "Create API Key",
        "API Keys",
        "API Settings",
        "Generate",
        "Mention Rate",
        "Average Rank",
        "Sample Count",
        "Citation Share",
        "Unmeasured",
        "Cohort",
        "Prompt",
        "Secret Key",
        "Model ID",
        "Base URL",
        "Owner",
        "Editor",
        "Viewer",
        "Perception Gaps",
        "Target Questions",
        "Brand Fact Library",
        "Worker 执行",
        "W3C guidance on presenting findings",
        "Schema.org Report",
        "Schema.org TechArticle",
        "Schema.org SoftwareApplication",
        "CiteAura measurement documentation",
    )
    values = list(catalog.values()) + [
        product_catalog["docs.byok_openai_step2"],
        product_catalog["docs.byok_claude_step2"],
        product_catalog["docs.byok_google_step2"],
        product_catalog["docs.byok_custom_step2"],
        product_catalog["docs.diag_gaps_h3"],
        product_catalog["docs.diag_questions_h3"],
        product_catalog["docs.diag_facts_h3"],
        product_catalog["docs.step_4_desc"],
        product_catalog["g1.sec2_p"],
        product_catalog["g1.sec3_p"],
    ]
    assert not [(phrase, value) for value in values for phrase in forbidden if phrase in value]


def test_landing_has_no_forbidden_brand_or_false_claims():
    response = client.get("/")
    lowered = response.text.lower()

    assert "geolook" not in lowered
    assert "保证上首页" not in response.text
    assert "保证提及" not in response.text
    assert "已通过 SOC 2" not in response.text


def test_landing_js_supports_international_locales():
    response = client.get("/site-assets/landing.js")
    assert response.status_code == 200
    assert "localStorage.setItem('ulang'" in response.text
    assert "function detectLocale()" in response.text
    assert "var LOCALES = ['en', 'zh', 'ja', 'ko', 'es', 'fr', 'de']" in response.text
    assert "fetch('/i18n/en.json')" in response.text
    assert "fetch('/i18n/' + state.locale + '.json')" in response.text
    assert "function publicValue(key, fallback, params)" in response.text
    assert "public.landing.preview_log_ready" in response.text
    assert "new WeakMap()" in response.text
    assert "function refreshPreviewLocale()" in response.text
    assert "previewState.hasResult" in response.text
    assert "data-preview-step" in response.text


def test_public_pages_load_shared_landing_localization():
    for path in ("/about", "/contact", "/privacy", "/terms", "/sample-report"):
        response = client.get(path)
        assert response.status_code == 200
        assert '/site-assets/landing.js?v=3.3' in response.text, path
    assert 'data-i18n-html="public.privacy.sec1"' in client.get("/privacy").text
    assert 'data-i18n-html="public.terms.sec1"' in client.get("/terms").text
    assert 'data-i18n-html="public.sample.sec1"' in client.get("/sample-report").text


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
    assert "<loc>https://citeaura.com/about</loc>" in sitemap_res.text
    assert "<loc>https://citeaura.com/contact</loc>" in sitemap_res.text
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
    assert "https://citeaura.com/about" in llms_res.text
    assert "https://citeaura.com/contact" in llms_res.text
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
    assert "Measure and diagnose AI brand visibility</h1>" in index.text
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
        assert f"{headline}</h1>" in page.text
        assert marker in page.text
        assert "does not guarantee" in page.text
        assert f'rel="canonical" href="https://citeaura.com{path}"' in page.text
        assert page.text.count('href="https://') >= 3
        assert "Sources</h2>" in page.text
        assert page.text.count("<h1") == 1
        assert '"@type": "FAQPage"' in page.text
        assert 'class="blog-related"' in page.text
        assert "By CiteAura Editorial Team" in page.text
        assert 'class="blog-cta"' in page.text
        assert 'href="/app?auth=register"' in page.text and "Start free trial</a>" in page.text
        title = re.search(r"<title(?:\s[^>]*)?>([^<]+)</title>", page.text)
        assert title is not None
        assert 55 <= len(title.group(1)) <= 70

    assert client.get("/blog/not-a-real-slug").status_code == 404


def test_homepage_keeps_slogan_h1_and_links_guides():
    response = client.get("/")
    assert 'id="hero-title" data-i18n="landing.hero_title"' in response.text
    assert "Find out why AI overlooks your brand" in response.text
    assert "AI answer → citation gap → page change → acceptance check → re-test" in response.text
    assert "Mention Rate" in response.text
    assert "Citation Rate" in response.text
    assert "View a sample report" in response.text
    assert 'id="primary-nav"' in response.text
    assert 'href="/blog" data-i18n="nav.guides">Guides</a>' in response.text
    assert 'class="header-status-badge"' not in response.text
    assert 'class="hero-status-badge"' not in response.text
    assert 'data-i18n="nav.status"' not in response.text
    assert 'id="blog"' in response.text
    assert 'href="/blog/measure-if-chatgpt-mentions-your-brand"' in response.text
    assert 'href="/blog/why-chatgpt-does-not-mention-my-brand"' in response.text
    assert 'href="/blog/gptbot-blocked-by-robots-txt"' in response.text
    assert 'href="/blog/what-to-put-in-llms-txt"' in response.text
    assert 'href="/blog/white-label-geo-diagnostic-report"' in response.text
