"""BYOK API Key 管理路由。"""

import re
import time
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from api.adapters.engine import CUSTOM_PROVIDER_CODE, ENGINE_KEY_ENV, with_tenant_context
from api.adapters.network import NetworkTargetError, validate_outbound_url
from api.adapters import sampling_modes
from api.auth.deps import get_current_user, require_owner
from api.db import get_db
from api.models import ApiKey, CustomProvider, Tenant, User
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


class CustomProviderPayload(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    base_url: str = Field(min_length=1, max_length=2048)
    api_key: str = Field(min_length=1, max_length=4096)
    model_id: str = Field(min_length=1, max_length=255)
    market: str = Field(default="both", pattern="^(cn|global|both)$")

    @field_validator("name", "model_id", "api_key")
    @classmethod
    def validate_text(cls, value: str):
        value = value.strip()
        if not value or "\n" in value or "\r" in value:
            raise ValueError("value must be a non-empty single line")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str):
        value = value.strip().rstrip("/")
        try:
            validate_outbound_url(value, require_https=True)
        except NetworkTargetError as exc:
            raise ValueError(str(exc)) from exc
        parsed = urlparse(value)
        if parsed.query or parsed.fragment:
            raise ValueError("base_url must not contain query or fragment")
        if parsed.path.endswith("/chat/completions"):
            value = value[: -len("/chat/completions")].rstrip("/")
        return value

def _error(status_code: int, message: str):
    raise HTTPException(status_code=status_code, detail={"error": message})


def _tenant_for_user(db: Session, user: User) -> Tenant:
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None:
        _error(status.HTTP_403_FORBIDDEN, "no_tenant_membership")
    return tenant


def _provider_code(tenant_id: int, name: str) -> str:
    """为租户生成稳定且不泄露原始名称的供应商代码。"""
    import hashlib

    digest = hashlib.sha256(f"{tenant_id}:{name}".encode("utf-8")).hexdigest()[:12]
    return f"custom_{digest}"


def _provider_response(row: CustomProvider, include_key=False):
    result = {
        "code": row.code,
        "name": row.name,
        "base_url": row.base_url,
        "model_id": row.model_id,
        "market": row.market or "both",
        "masked": mask_key(decrypt_key(row.encrypted_api_key)),
        "sampling_mode": sampling_modes.MODE_API,
    }
    if include_key:
        result["api_key"] = decrypt_key(row.encrypted_api_key)
    return result


def _test_custom_provider(provider: dict):
    """对 OpenAI-compatible chat/completions 发一条最小连接请求。"""
    code = provider["code"]
    with with_tenant_context("provider-test", "custom-provider-test", keys={code: provider["api_key"]}):
        try:
            response = requests.post(
                f"{provider['base_url']}/chat/completions",
                headers={
                    "Authorization": f"Bearer {provider['api_key']}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": provider["model_id"],
                    "messages": [{"role": "user", "content": "Reply with exactly OK."}],
                    "temperature": 0.7,
                },
                timeout=15,
            )
        except requests.exceptions.Timeout as exc:
            return {"ok": False, "error": f"Timeout: {exc}"}
        except requests.exceptions.RequestException as exc:
            return {"ok": False, "error": f"RequestException: {exc}"}
    if response.status_code != 200:
        return {"ok": False, "error": f"HTTP {response.status_code}"}
    try:
        data = response.json()
        answer = data["choices"][0]["message"].get("content") or ""
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return {"ok": False, "error": "provider_invalid_response"}
    return {
        "ok": True,
        "answer": answer,
        "raw_model": data.get("model", provider["model_id"]),
    }


def _custom_provider_connection_error(error):
    """返回稳定错误及可安全展示的供应商诊断码。"""
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "error": "custom_provider_connection_failed",
            "detail": _safe_provider_error(error),
        },
    )


@router.get("/custom")
def list_custom_providers(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """列出当前租户自定义供应商，不返回明文密钥。"""
    tenant = _tenant_for_user(db, current_user)
    rows = db.query(CustomProvider).filter(CustomProvider.tenant_id == tenant.id).order_by(CustomProvider.id).all()
    return {"providers": [_provider_response(row) for row in rows]}


@router.post("/custom/test")
def test_custom_provider(payload: CustomProviderPayload, current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
    """保存前验证自定义 OpenAI-compatible 供应商连接。"""
    tenant = _tenant_for_user(db, current_user)
    provider = payload.model_dump()
    provider["code"] = _provider_code(tenant.id, payload.name)
    started = time.monotonic()
    try:
        result = _test_custom_provider(provider)
        return {
            "ok": bool(result.get("ok")),
            "code": provider["code"],
            "model": provider["model_id"],
            "sampling_mode": sampling_modes.MODE_API,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": None if result.get("ok") else _safe_provider_error(result.get("error")),
        }
    except Exception as exc:  # noqa: BLE001 - provider failure is sanitized for the UI
        return {
            "ok": False,
            "code": provider["code"],
            "model": provider["model_id"],
            "sampling_mode": sampling_modes.MODE_API,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": _safe_provider_error(exc),
        }


@router.put("/custom")
def put_custom_provider(payload: CustomProviderPayload, current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
    """验证成功后新增或替换自定义供应商配置。"""
    tenant = _tenant_for_user(db, current_user)
    provider = payload.model_dump()
    provider["code"] = _provider_code(tenant.id, payload.name)
    try:
        result = _test_custom_provider(provider)
    except Exception as exc:  # noqa: BLE001 - provider failure is exposed only as a stable API error
        _custom_provider_connection_error(exc)
    if not result.get("ok"):
        _custom_provider_connection_error(result.get("error"))
    row = db.query(CustomProvider).filter(CustomProvider.tenant_id == tenant.id, CustomProvider.code == provider["code"]).first()
    if row is None:
        row = CustomProvider(tenant_id=tenant.id, code=provider["code"])
        db.add(row)
    row.name = provider["name"]
    row.base_url = provider["base_url"]
    row.model_id = provider["model_id"]
    row.market = provider["market"]
    row.encrypted_api_key = encrypt_key(provider["api_key"])
    db.commit()
    return {"provider": _provider_response(row)}


@router.delete("/custom/{code}")
def delete_custom_provider(code: str, current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
    """删除租户自定义供应商。"""
    code = code.strip().lower()
    if not CUSTOM_PROVIDER_CODE.fullmatch(code):
        _error(status.HTTP_404_NOT_FOUND, "custom_provider_not_found")
    tenant = _tenant_for_user(db, current_user)
    row = db.query(CustomProvider).filter(CustomProvider.tenant_id == tenant.id, CustomProvider.code == code).first()
    if row is None:
        _error(status.HTTP_404_NOT_FOUND, "custom_provider_not_found")
    db.delete(row)
    db.commit()
    return {"deleted": True, "code": code}


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

        with with_tenant_context(tenant.directory_slug, "keytest", keys={engine_code: secret}):
            result = sample.ask(engine_code, "Reply with exactly OK.", timeout=20)
        ok = bool(result.get("ok"))
        error = None if ok else _safe_provider_error(result.get("error"))
        return {
            "ok": ok,
            "engine": engine_code,
            "model": sample.model_for(engine_code),
            "sampling_mode": sampling_modes.for_provider(sample.PROVIDERS[engine_code]),
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": error,
        }
    except Exception as exc:  # noqa: BLE001 - provider failures are returned as a sanitized diagnostic
        return {
            "ok": False,
            "engine": engine_code,
            "model": None,
            "sampling_mode": sampling_modes.MODE_API,
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
