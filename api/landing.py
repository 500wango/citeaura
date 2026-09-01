"""Public landing pages and the message catalogs."""

import json
import os
from pathlib import Path
from xml.sax.saxutils import escape

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from api.i18n import SUPPORTED_LOCALES, load_all_catalogs, normalize_locale
from api.i18n.catalog import MESSAGES_DIR

router = APIRouter(include_in_schema=False)
WEB_ROOT = Path(__file__).resolve().parent.parent / "web"

# 站点公开域名，与各页 <link rel="canonical"> 必须一致。
# 不复用 config.public_base_url()：那是应用 origin（SSO 回调、分享链接），
# 本地默认 http://localhost:8000，与 canonical 声明的规范域名是两个不同概念。
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "https://citeaura.com").rstrip("/")

# 公开可索引页面的单一数据源。sitemap.xml 由此生成，BLOG_SLUGS 由此派生，
# web/llms.txt 的链接清单由 test_landing.py 断言与此一致。
# lastmod 显式维护而非取文件 mtime——git checkout 不保留 mtime，
# Docker 构建上下文也会改写它，取出来的会是不稳定的假数据。
PUBLIC_PAGES = (
    {"path": "/", "lastmod": "2026-08-20", "changefreq": "weekly", "priority": "1.0"},
    {"path": "/docs", "lastmod": "2026-08-20", "changefreq": "weekly", "priority": "0.8"},
    {"path": "/ai-visibility-audit", "lastmod": "2026-08-26", "changefreq": "monthly", "priority": "0.9"},
    {"path": "/for-agencies", "lastmod": "2026-08-26", "changefreq": "monthly", "priority": "0.8"},
    {"path": "/for-brands", "lastmod": "2026-08-26", "changefreq": "monthly", "priority": "0.8"},
    {"path": "/methodology", "lastmod": "2026-08-26", "changefreq": "monthly", "priority": "0.7"},
    {"path": "/pricing", "lastmod": "2026-08-26", "changefreq": "monthly", "priority": "0.7"},
    {"path": "/sample-report", "lastmod": "2026-08-23", "changefreq": "monthly", "priority": "0.8"},
    {"path": "/about", "lastmod": "2026-08-20", "changefreq": "monthly", "priority": "0.7"},
    {"path": "/contact", "lastmod": "2026-08-20", "changefreq": "monthly", "priority": "0.6"},
    {"path": "/blog", "lastmod": "2026-08-20", "changefreq": "weekly", "priority": "0.7"},
    {"path": "/blog/best-ai-visibility-tools", "lastmod": "2026-09-01", "changefreq": "monthly", "priority": "0.6"},
    {"path": "/blog/measure-if-chatgpt-mentions-your-brand", "lastmod": "2026-08-20", "changefreq": "monthly", "priority": "0.6"},
    {"path": "/blog/why-chatgpt-does-not-mention-my-brand", "lastmod": "2026-08-20", "changefreq": "monthly", "priority": "0.6"},
    {"path": "/blog/perplexity-citation-audit", "lastmod": "2026-09-01", "changefreq": "monthly", "priority": "0.6"},
    {"path": "/blog/google-ai-overviews-citation-guide", "lastmod": "2026-09-01", "changefreq": "monthly", "priority": "0.6"},
    {"path": "/blog/what-to-put-in-llms-txt", "lastmod": "2026-08-20", "changefreq": "monthly", "priority": "0.6"},
    {"path": "/blog/gptbot-blocked-by-robots-txt", "lastmod": "2026-08-20", "changefreq": "monthly", "priority": "0.6"},
    {"path": "/blog/ai-crawler-access-checklist", "lastmod": "2026-09-01", "changefreq": "monthly", "priority": "0.6"},
    {"path": "/blog/geo-vs-seo", "lastmod": "2026-09-01", "changefreq": "monthly", "priority": "0.6"},
    {"path": "/blog/extractability-audit", "lastmod": "2026-09-01", "changefreq": "monthly", "priority": "0.6"},
    {"path": "/blog/white-label-geo-diagnostic-report", "lastmod": "2026-08-20", "changefreq": "monthly", "priority": "0.6"},
    {"path": "/blog/brand-fact-library-guide", "lastmod": "2026-09-01", "changefreq": "monthly", "priority": "0.6"},
    {"path": "/blog/how-to-get-ai-to-cite-your-site", "lastmod": "2026-09-01", "changefreq": "monthly", "priority": "0.6"},
    {"path": "/blog/geo-blueprint-guide", "lastmod": "2026-09-01", "changefreq": "monthly", "priority": "0.6"},
    {"path": "/blog/sampling-modes-explained", "lastmod": "2026-09-01", "changefreq": "monthly", "priority": "0.6"},
    {"path": "/blog/citation-readiness-score", "lastmod": "2026-09-01", "changefreq": "monthly", "priority": "0.6"},
    {"path": "/blog/geo-verification-loop", "lastmod": "2026-09-01", "changefreq": "monthly", "priority": "0.6"},
    {"path": "/blog/ai-visibility-diagnosis-for-brands", "lastmod": "2026-09-01", "changefreq": "monthly", "priority": "0.6"},
    {"path": "/blog/sell-geo-retainers-with-delivery-packs", "lastmod": "2026-09-01", "changefreq": "monthly", "priority": "0.6"},
    {"path": "/blog/ai-search-directory-listings-guide", "lastmod": "2026-09-01", "changefreq": "monthly", "priority": "0.6"},
    {"path": "/privacy", "lastmod": "2026-08-19", "changefreq": "monthly", "priority": "0.3"},
    {"path": "/terms", "lastmod": "2026-08-19", "changefreq": "monthly", "priority": "0.3"},
)
BLOG_PREFIX = "/blog/"
BLOG_SLUGS = tuple(
    page["path"].removeprefix(BLOG_PREFIX) for page in PUBLIC_PAGES if page["path"].startswith(BLOG_PREFIX)
)


@router.get("/")
@router.head("/")
def serve_landing_page():
    """返回 CiteAura 公开 Landing Page。"""
    return FileResponse(WEB_ROOT / "index.html", media_type="text/html; charset=utf-8")


@router.get("/about")
@router.head("/about")
def serve_about_page():
    """返回 CiteAura 产品与证据边界说明页面。"""
    return FileResponse(WEB_ROOT / "about.html", media_type="text/html; charset=utf-8")


@router.get("/contact")
@router.head("/contact")
def serve_contact_page():
    """返回 CiteAura 联系与隐私请求页面。"""
    return FileResponse(WEB_ROOT / "contact.html", media_type="text/html; charset=utf-8")


@router.get("/sample-report")
@router.head("/sample-report")
def serve_sample_report():
    """返回无需登录的示例诊断报告，帮助访客理解首次交付价值。"""
    return FileResponse(WEB_ROOT / "sample-report.html", media_type="text/html; charset=utf-8")


@router.get("/privacy")
@router.head("/privacy")
def serve_privacy_page():
    """返回 CiteAura 隐私政策页面。"""
    return FileResponse(WEB_ROOT / "privacy.html", media_type="text/html; charset=utf-8")


@router.get("/terms")
@router.head("/terms")
def serve_terms_page():
    """返回 CiteAura 服务条款页面。"""
    return FileResponse(WEB_ROOT / "terms.html", media_type="text/html; charset=utf-8")


@router.get("/docs")
@router.head("/docs")
def serve_docs_page():
    """返回 CiteAura 文档与新手上手中心页面。"""
    return FileResponse(WEB_ROOT / "docs.html", media_type="text/html; charset=utf-8")


@router.get("/ai-visibility-audit")
@router.head("/ai-visibility-audit")
def serve_ai_visibility_audit_page():
    """返回面向高意图搜索的 AI visibility audit 支柱页。"""
    return FileResponse(WEB_ROOT / "ai-visibility-audit.html", media_type="text/html; charset=utf-8")


@router.get("/for-agencies")
@router.head("/for-agencies")
def serve_agencies_page():
    """返回面向 GEO/SEO 代理商的公开方案页。"""
    return FileResponse(WEB_ROOT / "for-agencies.html", media_type="text/html; charset=utf-8")


@router.get("/for-brands")
@router.head("/for-brands")
def serve_brands_page():
    """返回面向品牌增长团队的公开方案页。"""
    return FileResponse(WEB_ROOT / "for-brands.html", media_type="text/html; charset=utf-8")


@router.get("/methodology")
@router.head("/methodology")
def serve_methodology_page():
    """返回 CiteAura 的 GEO 测量方法论页面。"""
    return FileResponse(WEB_ROOT / "methodology.html", media_type="text/html; charset=utf-8")


@router.get("/pricing")
@router.head("/pricing")
def serve_pricing_page():
    """返回公开套餐与试用说明页面。"""
    return FileResponse(WEB_ROOT / "pricing.html", media_type="text/html; charset=utf-8")


@router.get("/blog")
@router.head("/blog")
def serve_blog_index():
    """返回可收录的 Guides 列表页。"""
    return FileResponse(WEB_ROOT / "blog" / "index.html", media_type="text/html; charset=utf-8")


@router.get("/blog/{slug}")
@router.head("/blog/{slug}")
def serve_blog_article(slug: str):
    """返回白名单内的静态长尾文章；未知 slug 返回 404。"""
    if slug not in BLOG_SLUGS:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    path = WEB_ROOT / "blog" / f"{slug}.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return FileResponse(path, media_type="text/html; charset=utf-8")


@router.get("/docs.js")
def serve_docs_script():
    """Return the CSP-compatible documentation behavior module."""
    return FileResponse(WEB_ROOT / "docs.js", media_type="application/javascript; charset=utf-8")


@router.get("/robots.txt")
def serve_robots_txt():
    """返回搜索引擎抓取策略文件 robots.txt。"""
    return FileResponse(WEB_ROOT / "robots.txt", media_type="text/plain; charset=utf-8")


def build_sitemap_xml():
    """由 PUBLIC_PAGES 生成 sitemap，避免与 BLOG_SLUGS、llms.txt 三处手工同步。"""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for page in PUBLIC_PAGES:
        lines.append("  <url>")
        lines.append(f"    <loc>{escape(SITE_BASE_URL + page['path'])}</loc>")
        lines.append(f"    <lastmod>{page['lastmod']}</lastmod>")
        lines.append(f"    <changefreq>{page['changefreq']}</changefreq>")
        lines.append(f"    <priority>{page['priority']}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


@router.get("/sitemap.xml")
@router.head("/sitemap.xml")
def serve_sitemap_xml():
    """返回由 PUBLIC_PAGES 生成的网站索引地图。"""
    return Response(
        content=build_sitemap_xml(),
        media_type="application/xml; charset=utf-8",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/manifest.webmanifest")
@router.head("/manifest.webmanifest")
def serve_web_manifest():
    """返回 PWA 清单，供移动端「添加到主屏」使用。"""
    return FileResponse(
        WEB_ROOT / "manifest.webmanifest",
        media_type="application/manifest+json; charset=utf-8",
    )


@router.get("/favicon.ico")
@router.head("/favicon.ico")
def serve_favicon_ico():
    """把爬虫与旧客户端对 /favicon.ico 的盲请求重定向到实际图标，消除 404 噪音。"""
    return RedirectResponse("/site-assets/favicon.png", status_code=308)


@router.get("/llms.txt")
@router.head("/llms.txt")
def serve_llms_txt():
    """返回 CiteAura 的公开机器可读产品说明。"""
    return FileResponse(WEB_ROOT / "llms.txt", media_type="text/plain; charset=utf-8")


@router.get("/i18n/{locale}.json")
def serve_i18n_catalog(locale: str):
    """Serve the English landing-page catalog."""
    code = normalize_locale(locale, default="")
    if code not in SUPPORTED_LOCALES:
        raise HTTPException(status_code=404, detail={"error": "locale_not_found"})
    path = MESSAGES_DIR / f"{code}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail={"error": "locale_not_found"})
    catalogs = load_all_catalogs()
    return JSONResponse(
        catalogs.get(code) or {},
        media_type="application/json; charset=utf-8",
        headers={"Cache-Control": "public, no-store, max-age=0"},
    )


@router.get("/i18n/public/{locale}.json")
def serve_public_i18n_catalog(locale: str):
    """Serve the public-page catalog kept separate from product UI copy."""
    code = normalize_locale(locale, default="")
    path = MESSAGES_DIR / "public" / f"{code}.json"
    if code not in SUPPORTED_LOCALES or not path.is_file():
        raise HTTPException(status_code=404, detail={"error": "locale_not_found"})
    return JSONResponse(
        json.loads(path.read_text("utf-8")),
        media_type="application/json; charset=utf-8",
        headers={"Cache-Control": "public, no-store, max-age=0"},
    )
