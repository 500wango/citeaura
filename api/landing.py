"""公开官网入口。"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


router = APIRouter(include_in_schema=False)
WEB_ROOT = Path(__file__).resolve().parent.parent / "web"


@router.get("/")
def serve_landing_page():
    """返回 DisvorAI 公开 Landing Page。"""
    return FileResponse(WEB_ROOT / "index.html", media_type="text/html; charset=utf-8")
