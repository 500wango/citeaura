"""只读 Public API、API Token 管理和最小 MCP 工具协议。"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from api.adapters import export as report_export, prompt_research
from api.auth.api_tokens import issue, require
from api.auth.deps import require_owner
from api.db import get_db
from api.models import ApiAccessToken, Project, Tenant, User
from api.projects import router as project_router


router = APIRouter(tags=["integrations"])


class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value):
        value = " ".join(value.strip().split())
        if not value:
            raise ValueError("name is required")
        return value


def _error(code, message):
    raise HTTPException(status_code=code, detail={"error": message})


def _tenant_for_owner(db, user):
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None:
        _error(status.HTTP_403_FORBIDDEN, "no_tenant_membership")
    return tenant


def _token_payload(row):
    return {
        "id": row.id,
        "name": row.name,
        "prefix": row.token_prefix,
        "scopes": json.loads(row.scopes or "[\"read\"]"),
        "last_used_at": row.last_used_at,
        "revoked_at": row.revoked_at,
        "created_at": row.created_at,
    }


@router.post("/api/v1/settings/api-tokens", status_code=status.HTTP_201_CREATED)
def create_api_token(
    payload: ApiTokenCreate,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    tenant = _tenant_for_owner(db, current_user)
    row, raw = issue(db, tenant, payload.name)
    db.commit()
    return {"token": raw, "warning": "Copy this token now. CiteAura never stores or shows it again.", "api_token": _token_payload(row)}


@router.get("/api/v1/settings/api-tokens")
def list_api_tokens(current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
    tenant = _tenant_for_owner(db, current_user)
    rows = db.query(ApiAccessToken).filter(ApiAccessToken.tenant_id == tenant.id).order_by(ApiAccessToken.id.desc()).all()
    return {"tokens": [_token_payload(row) for row in rows]}


@router.delete("/api/v1/settings/api-tokens/{token_id}")
def revoke_api_token(token_id: int, current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
    tenant = _tenant_for_owner(db, current_user)
    row = db.query(ApiAccessToken).filter(ApiAccessToken.id == token_id, ApiAccessToken.tenant_id == tenant.id).first()
    if row is None:
        _error(status.HTTP_404_NOT_FOUND, "api_token_not_found")
    row.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "token_id": row.id, "revoked_at": row.revoked_at}


def _integration_context(request: Request, db: Session):
    row = require(request, db)
    tenant = db.get(Tenant, row.tenant_id)
    if tenant is None or tenant.status != "active":
        _error(status.HTTP_401_UNAUTHORIZED, "api_token_invalid")
    return row, tenant


def _token_project(db, tenant, project_id):
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.tenant_id == tenant.id,
        Project.archived_at.is_(None),
        Project.status != "archived",
    ).first()
    if project is None:
        _error(status.HTTP_404_NOT_FOUND, "project_not_found")
    return project


@router.get("/api/v1/public-api/projects")
def public_api_projects(request: Request, db: Session = Depends(get_db)):
    _, tenant = _integration_context(request, db)
    rows = db.query(Project).filter(
        Project.tenant_id == tenant.id,
        Project.archived_at.is_(None),
        Project.status != "archived",
    ).order_by(Project.id.asc()).all()
    return {"projects": [{"id": row.id, "slug": row.slug, "url": row.url, "status": row.status, "market": row.market} for row in rows]}


@router.get("/api/v1/public-api/projects/{project_id}/report")
def public_api_report(project_id: int, request: Request, db: Session = Depends(get_db)):
    _, tenant = _integration_context(request, db)
    project = _token_project(db, tenant, project_id)
    return project_router._project_report_payload(db, tenant, project)


@router.get("/api/v1/public-api/projects/{project_id}/report.csv")
def public_api_report_csv(project_id: int, request: Request, db: Session = Depends(get_db)):
    _, tenant = _integration_context(request, db)
    project = _token_project(db, tenant, project_id)
    payload = project_router._project_report_payload(db, tenant, project)
    response = Response(
        content=report_export.report_csv(project.slug, payload["report"]),
        media_type="text/csv; charset=utf-8",
    )
    response.headers["Content-Disposition"] = f'attachment; filename="citeaura-{project.slug}-report.csv"'
    return response


@router.get("/api/v1/public-api/projects/{project_id}/prompt-research")
def public_api_prompt_research(project_id: int, request: Request, db: Session = Depends(get_db)):
    _, tenant = _integration_context(request, db)
    project = _token_project(db, tenant, project_id)
    with project_router.with_tenant_read_context(tenant, project.slug):
        return prompt_research.read(project.slug)


def _mcp_error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


@router.post("/api/v1/mcp")
def mcp(request: Request, payload: dict, db: Session = Depends(get_db)):
    """提供 MCP initialize/tools/list/tools/call 的只读子集。"""
    _integration_context(request, db)
    request_id = payload.get("id")
    method = payload.get("method")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": request_id, "result": {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "citeaura", "version": "1.0"},
        }}
    if method == "notifications/initialized":
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": [
            {"name": "list_projects", "description": "List active CiteAura projects", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "get_visibility_report", "description": "Read the latest labeled visibility report", "inputSchema": {"type": "object", "required": ["project_id"], "properties": {"project_id": {"type": "integer"}}}},
            {"name": "get_prompt_research", "description": "Read prompt research fan-out candidates", "inputSchema": {"type": "object", "required": ["project_id"], "properties": {"project_id": {"type": "integer"}}}},
        ]}}
    if method != "tools/call":
        return _mcp_error(request_id, -32601, "method_not_found")
    params = payload.get("params") or {}
    name = params.get("name")
    arguments = params.get("arguments") or {}
    try:
        if name == "list_projects":
            result = public_api_projects(request, db)
        elif name == "get_visibility_report":
            result = public_api_report(int(arguments.get("project_id")), request, db)
        elif name == "get_prompt_research":
            result = public_api_prompt_research(int(arguments.get("project_id")), request, db)
        else:
            return _mcp_error(request_id, -32602, "unknown_tool")
    except (TypeError, ValueError):
        return _mcp_error(request_id, -32602, "project_id_required")
    except HTTPException as exc:
        return _mcp_error(request_id, -32004, (exc.detail or {}).get("error", "tool_failed") if isinstance(exc.detail, dict) else "tool_failed")
    return {"jsonrpc": "2.0", "id": request_id, "result": {
        "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}],
        "structuredContent": result,
    }}
