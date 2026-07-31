"""FastAPI 应用入口。"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api import config
from api.adapters.exceptions import DistributedLockError
from api.auth.router import router as auth_router
from api.auth.sso import router as sso_router
from api.archive.router import router as archive_router
from api.billing.router import router as billing_router
from api.branding.router import router as branding_router
from api.integrations.router import router as integrations_router
from api.landing import WEB_ROOT, router as landing_router
from api.outreach.router import router as outreach_router
from api.publishing.router import router as publishing_router
from api.projects.router import router as projects_router
from api.settings.router import router as settings_router
from api.team.router import router as team_router
from api.ui import router as ui_router
from api.workspace.router import router as workspace_router


app = FastAPI(title="DisvorAI API", version="1.0.0")
app.mount("/site-assets", StaticFiles(directory=WEB_ROOT / "assets"), name="site-assets")
app.include_router(auth_router)
app.include_router(sso_router)
app.include_router(archive_router)
app.include_router(billing_router)
app.include_router(branding_router)
app.include_router(integrations_router)
app.include_router(outreach_router)
app.include_router(publishing_router)
app.include_router(projects_router)
app.include_router(settings_router)
app.include_router(team_router)
app.include_router(workspace_router)
app.include_router(landing_router)
app.include_router(ui_router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """为 API 和嵌入式 UI 添加基础浏览器安全策略。"""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if config.session_cookie_secure():
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.exception_handler(DistributedLockError)
async def distributed_lock_exception_handler(request: Request, exc: DistributedLockError):
    """分布式锁不可用时返回可重试错误。"""
    return JSONResponse(
        status_code=503,
        content={"error": str(exc)},
        headers={"Retry-After": "1"},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """统一返回 API 错误 JSON，同时保留 FastAPI 的标准 detail 兼容性。"""
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        content = exc.detail
    else:
        content = {"detail": exc.detail}
    return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)


@app.get("/api/v1/health")
def health_check():
    """返回服务健康状态。"""
    return {"status": "ok"}
