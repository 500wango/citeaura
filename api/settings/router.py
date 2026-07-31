"""BYOK API Key 管理路由。"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from api.adapters.engine import ENGINE_KEY_ENV
from api.auth.deps import get_current_user
from api.db import get_db
from api.models import ApiKey, Tenant, User
from api.settings.crypto import encrypt_key, mask_key


router = APIRouter(prefix="/api/v1/settings/keys", tags=["settings"])
SUPPORTED_ENGINE_CODES = frozenset(ENGINE_KEY_ENV)


class KeyPayload(BaseModel):
    engine_code: str = Field(min_length=1, max_length=64)
    key_value: str = Field(min_length=1, max_length=4096)

    @field_validator("engine_code")
    @classmethod
    def validate_engine_code(cls, value: str):
        value = value.strip().lower()
        if value not in SUPPORTED_ENGINE_CODES:
            raise ValueError("unsupported engine_code")
        return value

    @field_validator("key_value")
    @classmethod
    def validate_key_value(cls, value: str):
        value = value.strip()
        if not value or "\n" in value or "\r" in value:
            raise ValueError("key_value must be a non-empty single line")
        return value


def _error(status_code: int, message: str):
    raise HTTPException(status_code=status_code, detail={"error": message})


def _tenant_for_user(db: Session, user: User) -> Tenant:
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None:
        _error(status.HTTP_403_FORBIDDEN, "no_tenant_membership")
    return tenant


@router.put("")
def put_key(payload: KeyPayload, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """新增或替换当前租户的引擎 API Key。"""
    tenant = _tenant_for_user(db, current_user)
    encrypted_value = encrypt_key(payload.key_value)
    row = (
        db.query(ApiKey)
        .filter(ApiKey.tenant_id == tenant.id, ApiKey.engine_code == payload.engine_code)
        .first()
    )
    if row is None:
        row = ApiKey(
            tenant_id=tenant.id,
            engine_code=payload.engine_code,
            encrypted_value=encrypted_value,
        )
        db.add(row)
    else:
        row.encrypted_value = encrypted_value
    db.commit()
    return {"engine_code": payload.engine_code, "masked": mask_key(payload.key_value)}


@router.get("")
def list_keys(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """列出已配置引擎，绝不返回明文。"""
    tenant = _tenant_for_user(db, current_user)
    rows = (
        db.query(ApiKey)
        .filter(ApiKey.tenant_id == tenant.id, ApiKey.engine_code.in_(SUPPORTED_ENGINE_CODES))
        .order_by(ApiKey.engine_code)
        .all()
    )
    items = []
    for row in rows:
        # 只在请求内解密用于掩码，响应和日志都不携带明文。
        from api.settings.crypto import decrypt_key

        items.append({"engine_code": row.engine_code, "masked": mask_key(decrypt_key(row.encrypted_value))})
    return {"keys": items}


@router.delete("/{engine_code}")
def delete_key(engine_code: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """删除当前租户指定引擎的 API Key。"""
    engine_code = engine_code.strip().lower()
    if engine_code not in SUPPORTED_ENGINE_CODES:
        _error(status.HTTP_404_NOT_FOUND, "key_not_found")
    tenant = _tenant_for_user(db, current_user)
    row = (
        db.query(ApiKey)
        .filter(ApiKey.tenant_id == tenant.id, ApiKey.engine_code == engine_code)
        .first()
    )
    if row is None:
        _error(status.HTTP_404_NOT_FOUND, "key_not_found")
    db.delete(row)
    db.commit()
    return {"deleted": True, "engine_code": engine_code}
