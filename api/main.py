"""FastAPI 应用入口。"""

import time
from urllib.parse import urlparse, urlsplit, urlunsplit

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy.exc import IntegrityError

from api import config
from api.adapters.exceptions import DistributedLockError
from api.admin.router import router as admin_router
from api.analytics.router import router as analytics_router
from api.integrations.router import router as integrations_router
from api.auth.router import router as auth_router
from api.auth.sso import router as sso_router
from api.archive.router import router as archive_router
from api.billing.router import router as billing_router
from api.branding.router import router as branding_router
from api.landing import WEB_ROOT, router as landing_router
from api.db import get_db
from api.outreach.router import router as outreach_router
from api.publishing.router import router as publishing_router
from api.projects.public import router as public_projects_router
from api.projects.router import router as projects_router
from api.settings.router import router as settings_router
from api.team.router import router as team_router
from api.ui import router as ui_router
from api.workspace.router import router as workspace_router
from api.readiness import readiness_checks
from api.rate_limit import AUTH_PATHS, RateLimitUnavailable, check_request


_docs_url = "/api/docs" if config.api_docs_enabled() else None
_redoc_url = "/api/redoc" if config.api_docs_enabled() else None
app = FastAPI(title="CiteAura API", version="1.0.0", docs_url=_docs_url, redoc_url=_redoc_url)
_public_host = urlparse(config.public_base_url()).hostname or "localhost"
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=sorted({"localhost", "127.0.0.1", "testserver", _public_host, f"*.{_public_host}"}),
)
app.mount("/site-assets", StaticFiles(directory=WEB_ROOT / "assets"), name="site-assets")
app.mount("/app", StaticFiles(directory=WEB_ROOT / "app", html=True), name="app")
app.mount("/admin", StaticFiles(directory=WEB_ROOT / "admin", html=True), name="admin")
app.include_router(admin_router)
app.include_router(analytics_router)
app.include_router(integrations_router)
app.include_router(auth_router)
app.include_router(sso_router)
app.include_router(archive_router)
app.include_router(billing_router)
app.include_router(branding_router)
app.include_router(outreach_router)
app.include_router(publishing_router)
app.include_router(public_projects_router)
app.include_router(projects_router)
app.include_router(settings_router)
app.include_router(team_router)
app.include_router(workspace_router)
app.include_router(landing_router)
app.include_router(ui_router)


_NON_PUBLIC_SLASH_PREFIXES = ("/api/", "/app/", "/admin/", "/files/", "/site-assets/")


def _public_canonical_redirect(request: Request):
    """Build an HTTPS-safe canonical URL for public trailing-slash variants."""
    path = request.url.path
    if path == "/" or not path.endswith("/") or path.startswith(_NON_PUBLIC_SLASH_PREFIXES):
        return None
    base = urlsplit(config.public_base_url())
    if not base.scheme or not base.netloc:
        return None
    target = urlunsplit((base.scheme, base.netloc, path.rstrip("/"), request.url.query, ""))
    return RedirectResponse(url=target, status_code=308)


@app.middleware("http")
async def canonical_public_paths(request: Request, call_next):
    """Keep public pages on one permanent, non-trailing-slash URL."""
    redirect = _public_canonical_redirect(request)
    if redirect is not None:
        return redirect
    return await call_next(request)


@app.middleware("http")
async def api_rate_limiter(request: Request, call_next):
    """对 API 请求应用共享 Redis 配额。"""
    try:
        decision = check_request(request)
    except RateLimitUnavailable as exc:
        if request.url.path in AUTH_PATHS:
            return JSONResponse(
                status_code=503,
                content={"error": str(exc)},
                headers={"Retry-After": "1"},
            )
        decision = None
    if decision is not None and not decision.allowed:
        retry_after = max(1, decision.reset_at - int(time.time()))
        return JSONResponse(
            status_code=429,
            content={"error": "rate_limit_exceeded", "detail": "request limit exceeded"},
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(decision.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(decision.reset_at),
            },
        )
    response = await call_next(request)
    if decision is not None:
        response.headers["X-RateLimit-Limit"] = str(decision.limit)
        response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        response.headers["X-RateLimit-Reset"] = str(decision.reset_at)
    return response


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """为 API 和嵌入式 UI 添加基础浏览器安全策略。"""
    response = await call_next(request)
    if request.url.path == "/app" or request.url.path.startswith("/app/"):
        response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
    elif request.url.path.startswith("/site-assets/"):
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable" if request.query_params.get("v") else "public, max-age=86400"
        )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/api/v1/") and "Cache-Control" not in response.headers:
        response.headers["Cache-Control"] = "private, no-store"
    elif request.url.path.startswith("/app/"):
        response.headers["Cache-Control"] = "no-cache"
    if request.url.path.startswith("/files/"):
        response.headers["Content-Security-Policy"] = (
            "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data: blob: https:; "
            "font-src data:; connect-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        )
    else:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
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


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    """把活动任务唯一约束竞争转换成稳定的 409。"""
    detail = str(getattr(exc, "orig", exc))
    if "uq_jobs_project_active" in detail or "UNIQUE constraint failed: jobs.project_id" in detail:
        return JSONResponse(status_code=409, content={"error": "project_job_already_running"})
    if "uq_projects_tenant_slug" in detail or "UNIQUE constraint failed: projects.tenant_id, projects.slug" in detail:
        return JSONResponse(status_code=409, content={"error": "project_already_exists"})
    return JSONResponse(status_code=500, content={"error": "database_integrity_error"})


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


@app.get("/api/v1/health/ready")
def readiness_check(db=Depends(get_db)):
    """仅在生产关键依赖全部就绪时返回 200。"""
    result = readiness_checks(db)
    return JSONResponse(status_code=200 if result["status"] == "ready" else 503, content=result)
