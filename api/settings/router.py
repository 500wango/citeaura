"""BYOK API Key 管理路由。"""

import re
import time

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from api.adapters.engine import ENGINE_KEY_ENV, with_tenant_context
from api.auth.deps import get_current_user, require_owner
from api.db import get_db
from api.models import ApiKey, Tenant, User
from api.settings.crypto import decrypt_key, encrypt_key, mask_key


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
def put_key(payload: KeyPayload, current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
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
        items.append({"engine_code": row.engine_code, "masked": mask_key(decrypt_key(row.encrypted_value))})
    return {"keys": items}


@router.post("/{engine_code}/test")
def test_key(engine_code: str, current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
    """用一条最小请求验证 Key，响应不包含密钥或供应商原文。"""
    engine_code = engine_code.strip().lower()
    if engine_code not in SUPPORTED_ENGINE_CODES:
        _error(status.HTTP_404_NOT_FOUND, "key_not_found")
    tenant = _tenant_for_user(db, current_user)
    row = db.query(ApiKey).filter(ApiKey.tenant_id == tenant.id, ApiKey.engine_code == engine_code).first()
    if row is None:
        _error(status.HTTP_404_NOT_FOUND, "key_not_found")
    secret = decrypt_key(row.encrypted_value)
    started = time.monotonic()
    try:
        import sample

        with with_tenant_context(tenant.name, "keytest", keys={engine_code: secret}):
            result = sample.ask(engine_code, "Reply with exactly OK.", timeout=20)
        ok = bool(result.get("ok"))
        error = None if ok else _safe_provider_error(result.get("error"))
        return {
            "ok": ok,
            "engine": engine_code,
            "model": sample.model_for(engine_code),
            "sampling_mode": "API·联网检索" if sample.PROVIDERS[engine_code].get("search") else "API·参数化知识",
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": error,
        }
    except Exception as exc:  # noqa: BLE001 - provider failures are returned as a sanitized diagnostic
        return {
            "ok": False,
            "engine": engine_code,
            "model": None,
            "sampling_mode": "API·参数化知识",
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": _safe_provider_error(exc),
        }


def _safe_provider_error(error):
    """压缩供应商错误，避免返回响应正文、Key 或请求细节。"""
    text = str(error or "provider_request_failed")
    match = re.search(r"HTTP\s+(\d{3})", text, re.IGNORECASE)
    if match:
        return f"provider_http_{match.group(1)}"
    if "timeout" in text.lower() or "timedout" in text.lower():
        return "provider_timeout"
    return "provider_request_failed"


@router.delete("/{engine_code}")
def delete_key(engine_code: str, current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
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
