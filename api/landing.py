"""公开官网入口与 i18n 消息目录。"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from api.i18n import SUPPORTED_LOCALES, load_all_catalogs, normalize_locale
from api.i18n.catalog import MESSAGES_DIR

router = APIRouter(include_in_schema=False)
WEB_ROOT = Path(__file__).resolve().parent.parent / "web"


@router.get("/")
def serve_landing_page():
    """返回 CiteAura 公开 Landing Page。"""
    return FileResponse(WEB_ROOT / "index.html", media_type="text/html; charset=utf-8")


@router.get("/privacy")
def serve_privacy_page():
    """返回 CiteAura 隐私政策页面。"""
    return FileResponse(WEB_ROOT / "privacy.html", media_type="text/html; charset=utf-8")


@router.get("/terms")
def serve_terms_page():
    """返回 CiteAura 服务条款页面。"""
    return FileResponse(WEB_ROOT / "terms.html", media_type="text/html; charset=utf-8")


@router.get("/docs")
def serve_docs_page():
    """返回 CiteAura 文档与新手上手中心页面。"""
    return FileResponse(WEB_ROOT / "docs.html", media_type="text/html; charset=utf-8")


@router.get("/i18n/{locale}.json")
def serve_i18n_catalog(locale: str):
    """提供落地页与共享文案目录（en 为默认回退基线）。"""
    code = normalize_locale(locale, default="")
    if code not in SUPPORTED_LOCALES:
        raise HTTPException(status_code=404, detail={"error": "locale_not_found"})
    path = MESSAGES_DIR / f"{code}.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail={"error": "locale_not_found"})
    catalogs = load_all_catalogs()
    return JSONResponse(catalogs.get(code) or {}, media_type="application/json; charset=utf-8")
