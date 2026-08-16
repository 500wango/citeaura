"""外链联络草稿、SMTP 配置与人工确认发送 API。"""

import json
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from api.adapters import outreach
from api.adapters.engine import job_log_path, with_tenant_context, with_tenant_read_context
from api.auth.deps import get_current_user, require_editor, require_owner
from api.db import get_db
from api.models import IntegrationCredential, Job, Project, Tenant, User
from api.settings.crypto import encrypt_key
from api.worker.tasks import task_send_outreach


router = APIRouter(prefix="/api/v1/projects/{project_id}/outreach", tags=["outreach"])
SMTP_PROVIDER = "outreach_smtp"


class SmtpConfigRequest(BaseModel):
    host: str = Field(min_length=1, max_length=253)
    port: int
    security_mode: str = "starttls"
    username: str = Field(default="", max_length=320)
    password: str | None = Field(default=None, max_length=4096)
    from_email: str = Field(min_length=3, max_length=320)
    from_name: str = Field(default="", max_length=120)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", value):
            raise ValueError("invalid SMTP host")
        return value

    @field_validator("port")
    @classmethod
    def validate_port(cls, value):
        if value not in (25, 465, 587, 2525):
            raise ValueError("unsupported SMTP port")
        return value

    @field_validator("security_mode")
    @classmethod
    def validate_security_mode(cls, value):
        if value not in ("starttls", "ssl"):
            raise ValueError("security_mode must be starttls or ssl")
        return value

    @field_validator("username", "from_name")
    @classmethod
    def normalize_text(cls, value):
        value = value.strip()
        if "\n" in value or "\r" in value:
            raise ValueError("invalid SMTP text field")
        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value):
        if value is None:
            return value
        if not value or "\n" in value or "\r" in value:
            raise ValueError("invalid SMTP password")
        return value

    @field_validator("from_email")
    @classmethod
    def validate_from_email(cls, value):
        value = value.strip().lower()
        if not outreach.EMAIL_PATTERN.fullmatch(value):
            raise ValueError("invalid from_email")
        return value


class DraftCreateRequest(BaseModel):
    ticket_id: str = Field(min_length=1, max_length=128)
    recipient_email: str = Field(min_length=3, max_length=320)


class DraftUpdateRequest(BaseModel):
    revision: int = Field(ge=1)
    recipient_email: str = Field(min_length=3, max_length=320)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)


class SendRequest(BaseModel):
    revision: int = Field(ge=1)
    confirmed: bool = False
    confirmation_text: str = Field(default="", max_length=200)


def _error(status_code, message, detail=None):
    body = {"error": message}
    if detail:
        body["detail"] = detail
    raise HTTPException(status_code=status_code, detail=body)


def _tenant_project(db, user, project_id):
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None:
        _error(status.HTTP_403_FORBIDDEN, "no_tenant_membership")
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.tenant_id == tenant.id,
    ).first()
    if project is None:
        _error(status.HTTP_404_NOT_FOUND, "project_not_found")
    return tenant, project


def _smtp_row(db, tenant_id):
    return db.query(IntegrationCredential).filter(
        IntegrationCredential.tenant_id == tenant_id,
        IntegrationCredential.provider == SMTP_PROVIDER,
    ).first()


def _smtp_payload(row):
    if row is None:
        return {"configured": False}
    try:
        settings = json.loads(row.config_json or "{}")
    except (TypeError, ValueError):
        settings = {}
    return {"configured": True, **settings}


def _overview(db, tenant, project, can_edit):
    with with_tenant_read_context(tenant, project.slug):
        drafts = outreach.list_drafts(project.slug)
    return {
        "project_id": project.id,
        "can_edit": can_edit,
        "smtp": _smtp_payload(_smtp_row(db, tenant.id)),
        "drafts": drafts,
        "confirmation_required": True,
        "confirmation_format": "SEND <draft_id>",
    }


@router.get("")
def outreach_overview(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回 SMTP 连接状态、草稿与发送记录。"""
    tenant, project = _tenant_project(db, current_user, project_id)
    return _overview(db, tenant, project, current_user.tenant_role == "owner")


@router.put("/smtp")
def configure_smtp(
    project_id: int,
    payload: SmtpConfigRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """保存租户级 SMTP 凭证；项目路径仅用于租户隔离。"""
    tenant, project = _tenant_project(db, current_user, project_id)
    row = _smtp_row(db, tenant.id)
    if row is None:
        if payload.username and payload.password is None:
            _error(status.HTTP_400_BAD_REQUEST, "smtp_password_required")
        row = IntegrationCredential(tenant_id=tenant.id, provider=SMTP_PROVIDER)
        db.add(row)
    from api.settings.crypto import decrypt_key

    if row.encrypted_value:
        try:
            old_credentials = json.loads(decrypt_key(row.encrypted_value))
        except (ValueError, TypeError):
            old_credentials = {}
    else:
        old_credentials = {}
    password = payload.password if payload.password is not None else old_credentials.get("password", "")
    if payload.username and not password:
        _error(status.HTTP_400_BAD_REQUEST, "smtp_password_required")
    row.encrypted_value = encrypt_key(json.dumps({"username": payload.username, "password": password}))
    row.config_json = json.dumps({
        "host": payload.host,
        "port": payload.port,
        "security_mode": payload.security_mode,
        "username": payload.username,
        "from_email": payload.from_email,
        "from_name": payload.from_name,
        "password_configured": bool(password),
    }, sort_keys=True)
    db.commit()
    return _overview(db, tenant, project, True)


@router.delete("/smtp")
def delete_smtp(
    project_id: int,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """删除租户级 SMTP 凭证，历史草稿和发送记录保持不变。"""
    tenant, project = _tenant_project(db, current_user, project_id)
    row = _smtp_row(db, tenant.id)
    if row is None:
        _error(status.HTTP_404_NOT_FOUND, "smtp_not_configured")
    db.delete(row)
    db.commit()
    return _overview(db, tenant, project, True)


@router.post("/drafts", status_code=status.HTTP_201_CREATED)
def create_outreach_draft(
    project_id: int,
    payload: DraftCreateRequest,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """从 offsite 工单生成一封待人工编辑的联络草稿。"""
    tenant, project = _tenant_project(db, current_user, project_id)
    try:
        with with_tenant_context(tenant.directory_slug, project.slug):
            import tasks as engine_tasks

            ticket = next(
                (
                    item for item in engine_tasks.load(project.slug).get("tasks", [])
                    if item.get("id") == payload.ticket_id
                ),
                None,
            )
            if ticket is None:
                raise outreach.OutreachError("ticket_not_found")
            return {"draft": outreach.create_draft(project.slug, ticket, payload.recipient_email)}
    except outreach.OutreachError as exc:
        _error(status.HTTP_400_BAD_REQUEST, str(exc))


@router.put("/drafts/{draft_id}")
def update_outreach_draft(
    project_id: int,
    draft_id: str,
    payload: DraftUpdateRequest,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """按 revision 更新草稿，避免覆盖他人或旧页面修改。"""
    tenant, project = _tenant_project(db, current_user, project_id)
    try:
        with with_tenant_context(tenant.directory_slug, project.slug):
            draft = outreach.update_draft(
                project.slug,
                draft_id,
                payload.revision,
                payload.recipient_email,
                payload.subject,
                payload.body,
            )
        return {"draft": draft}
    except outreach.OutreachError as exc:
        code = status.HTTP_409_CONFLICT if str(exc) == "outreach_revision_conflict" else status.HTTP_400_BAD_REQUEST
        _error(code, str(exc))


@router.post("/drafts/{draft_id}/send", status_code=status.HTTP_202_ACCEPTED)
def send_outreach_draft(
    project_id: int,
    draft_id: str,
    payload: SendRequest,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """人工确认最终快照后投递发送任务。"""
    tenant, project = _tenant_project(db, current_user, project_id)
    if not payload.confirmed:
        _error(status.HTTP_400_BAD_REQUEST, "outreach_confirmation_required")
    if _smtp_row(db, tenant.id) is None:
        _error(status.HTTP_409_CONFLICT, "smtp_not_configured")
    active = db.query(Job.id).filter(
        Job.project_id == project.id,
        Job.status.in_(("queued", "running")),
    ).first()
    if active is not None:
        _error(status.HTTP_409_CONFLICT, "project_job_already_running")
    try:
        with with_tenant_context(tenant.directory_slug, project.slug):
            outreach.confirm_and_queue(
                project.slug,
                draft_id,
                payload.revision,
                current_user.id,
                payload.confirmation_text,
            )
    except outreach.OutreachError as exc:
        code = status.HTTP_409_CONFLICT if str(exc) == "outreach_revision_conflict" else status.HTTP_400_BAD_REQUEST
        _error(code, str(exc))
    job = Job(project_id=project.id, action="outreach_send", status="queued", request_json=json.dumps({"draft_id": draft_id}))
    db.add(job)
    project.status = "processing"
    db.commit()
    db.refresh(job)
    job.log_path = str(job_log_path(tenant.directory_slug, project.slug, job.id))
    db.commit()
    try:
        task_send_outreach.delay(tenant.directory_slug, project.slug, draft_id, job_id=job.id)
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.finished_at = datetime.now(timezone.utc)
        project.status = "failed"
        db.commit()
        with with_tenant_context(tenant.directory_slug, project.slug):
            outreach.restore_after_queue_failure(project.slug, draft_id, payload.revision, job.error)
        _error(status.HTTP_503_SERVICE_UNAVAILABLE, "worker_unavailable")
    return {"job_id": job.id, "project_id": project.id, "draft_id": draft_id}
