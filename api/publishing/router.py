"""租户隔离的内容发布 API。"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from api.adapters import publishing
from api.adapters.engine import with_tenant_context
from api.adapters.exceptions import GeoEngineError
from api.auth.deps import get_current_user, require_editor, require_owner
from api.db import get_db
from api.models import ApiKey, Project, Tenant, User
from api.settings.crypto import decrypt_key, encrypt_key


router = APIRouter(prefix="/api/v1/projects/{project_id}/publishing", tags=["publishing"])


class PublisherConfigRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    credentials: dict[str, str | None] = Field(default_factory=dict)
    publisher_config: dict[str, str] | None = Field(default=None, alias="config")

    @field_validator("credentials")
    @classmethod
    def validate_credentials(cls, values):
        for name, value in values.items():
            if not name or len(name) > 64:
                raise ValueError("invalid credential name")
            if value is not None and (not value.strip() or len(value) > 4096 or "\n" in value or "\r" in value):
                raise ValueError("credential must be a non-empty single line or null")
        return values


class PublishRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    title: str = Field(default="", max_length=300)
    confirmed: bool = False


def _error(status_code, message, detail=None):
    body = {"error": message}
    if detail:
        body["detail"] = detail
    raise HTTPException(status_code=status_code, detail=body)


def _tenant_project(db: Session, user: User, project_id: int):
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None:
        _error(status.HTTP_403_FORBIDDEN, "no_tenant_membership")
    project = db.query(Project).filter(Project.id == project_id, Project.tenant_id == tenant.id).first()
    if project is None:
        _error(status.HTTP_404_NOT_FOUND, "project_not_found")
    return tenant, project


def _configured_codes(db, tenant_id):
    prefix = f"{publishing.CREDENTIAL_PREFIX}%"
    return {
        row.engine_code
        for row in db.query(ApiKey.engine_code).filter(ApiKey.tenant_id == tenant_id, ApiKey.engine_code.like(prefix))
    }


def _credentials(db, tenant_id, platform):
    mapping = publishing.credential_map(platform)
    rows = db.query(ApiKey).filter(ApiKey.tenant_id == tenant_id, ApiKey.engine_code.in_(mapping)).all()
    return {mapping[row.engine_code]: decrypt_key(row.encrypted_value) for row in rows}


def _overview(db, tenant, project):
    with with_tenant_context(tenant.name, project.slug):
        return publishing.overview(project.slug, _configured_codes(db, tenant.id))


@router.get("")
def publishing_overview(
    project_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出渠道就绪状态、非敏感配置和发布记录。"""
    tenant, project = _tenant_project(db, current_user, project_id)
    try:
        return _overview(db, tenant, project)
    except (GeoEngineError, ValueError) as exc:
        _error(status.HTTP_400_BAD_REQUEST, "publishing_operation_failed", str(exc))


@router.put("/{platform}")
def update_publisher(
    project_id: int,
    platform: str,
    payload: PublisherConfigRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """保存渠道凭证和项目级非敏感配置。"""
    tenant, project = _tenant_project(db, current_user, project_id)
    try:
        allowed = publishing.credential_map(platform)
        unknown = sorted(set(payload.credentials) - set(allowed.values()))
        if unknown:
            raise ValueError("unsupported publisher credentials: " + ", ".join(unknown))
        publishing.validate_credentials(platform, payload.credentials)
        credential_changes = {
            publishing.credential_code(platform, env_name): None if value is None else encrypt_key(value.strip())
            for env_name, value in payload.credentials.items()
        }
        if payload.publisher_config is not None:
            with with_tenant_context(tenant.name, project.slug):
                publishing.save_config(project.slug, platform, payload.publisher_config)

        for code, encrypted in credential_changes.items():
            row = db.query(ApiKey).filter(ApiKey.tenant_id == tenant.id, ApiKey.engine_code == code).first()
            if encrypted is None:
                if row is not None:
                    db.delete(row)
                continue
            if row is None:
                db.add(ApiKey(tenant_id=tenant.id, engine_code=code, encrypted_value=encrypted))
            else:
                row.encrypted_value = encrypted
        db.commit()
        return {"ok": True, **_overview(db, tenant, project)}
    except (GeoEngineError, RuntimeError, ValueError) as exc:
        db.rollback()
        _error(status.HTTP_400_BAD_REQUEST, "publisher_config_invalid", str(exc))


@router.post("/{platform}")
def publish_content(
    project_id: int,
    platform: str,
    payload: PublishRequest,
    current_user: User = Depends(require_editor),
    db: Session = Depends(get_db),
):
    """经用户明确确认后，把项目成稿发送到指定渠道。"""
    tenant, project = _tenant_project(db, current_user, project_id)
    if not payload.confirmed:
        _error(status.HTTP_400_BAD_REQUEST, "publish_confirmation_required")
    try:
        credentials = _credentials(db, tenant.id, platform)
        with with_tenant_context(tenant.name, project.slug, credentials):
            state = publishing.overview(project.slug, _configured_codes(db, tenant.id))
            publisher = next(item for item in state["publishers"] if item["code"] == platform)
            if not publisher["ready"]:
                return {"ok": False, "error": "发布渠道尚未就绪：" + "、".join(publisher["missing"])}
            return publishing.publish(project.slug, platform, payload.path, payload.title.strip())
    except (GeoEngineError, RuntimeError, ValueError) as exc:
        _error(status.HTTP_400_BAD_REQUEST, "publishing_operation_failed", str(exc))
