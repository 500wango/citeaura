"""FastAPI 应用入口。"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from api.auth.router import router as auth_router
from api.billing.router import router as billing_router
from api.branding.router import router as branding_router
from api.publishing.router import router as publishing_router
from api.projects.router import router as projects_router
from api.settings.router import router as settings_router
from api.team.router import router as team_router
from api.ui import router as ui_router
from api.workspace.router import router as workspace_router


app = FastAPI(title="DisvorAI API", version="1.0.0")
app.include_router(auth_router)
app.include_router(billing_router)
app.include_router(branding_router)
app.include_router(publishing_router)
app.include_router(projects_router)
app.include_router(settings_router)
app.include_router(team_router)
app.include_router(workspace_router)
app.include_router(ui_router)


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
