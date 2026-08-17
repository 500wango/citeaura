"""Public landing pages and the English message catalog."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from api.i18n import SUPPORTED_LOCALES, load_all_catalogs, normalize_locale
from api.i18n.catalog import MESSAGES_DIR

router = APIRouter(include_in_schema=False)
WEB_ROOT = Path(__file__).resolve().parent.parent / "web"


@router.get("/")
@router.head("/")
def serve_landing_page():
    """返回 CiteAura 公开 Landing Page。"""
    return FileResponse(WEB_ROOT / "index.html", media_type="text/html; charset=utf-8")


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


@router.get("/docs.js")
def serve_docs_script():
    """Return the CSP-compatible documentation behavior module."""
    return FileResponse(WEB_ROOT / "docs.js", media_type="application/javascript; charset=utf-8")


@router.get("/robots.txt")
def serve_robots_txt():
    """返回搜索引擎抓取策略文件 robots.txt。"""
    return FileResponse(WEB_ROOT / "robots.txt", media_type="text/plain; charset=utf-8")


@router.get("/sitemap.xml")
def serve_sitemap_xml():
    """返回网站索引地图 sitemap.xml。"""
    return FileResponse(WEB_ROOT / "sitemap.xml", media_type="application/xml; charset=utf-8")


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
    return JSONResponse(catalogs.get(code) or {}, media_type="application/json; charset=utf-8")
