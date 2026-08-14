"""密码哈希和 JWT 安全工具。"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from api import config


JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 30
ACCESS_TOKEN_COOKIE = "citeaura_access_token"
REFRESH_TOKEN_COOKIE = "citeaura_refresh_token"


def _jwt_secret():
    """读取 JWT 密钥；生产环境必须显式配置。"""
    secret = config.jwt_secret()
    if not secret:
        raise RuntimeError("JWT_SECRET is not configured")
    return secret


def hash_password(password: str) -> str:
    """使用 bcrypt 哈希密码。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """验证明文密码是否匹配 bcrypt 哈希。"""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return False


def create_token(
    user_id: int,
    tenant_id: int,
    token_type: str,
    expires_delta: timedelta,
    extra_claims: dict | None = None,
) -> str:
    """签发带用户、租户和类型声明的 JWT。"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    payload.update(extra_claims or {})
    return jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def create_access_token(user_id: int, tenant_id: int, session_version: int = 0) -> str:
    """签发 access token。"""
    return create_token(user_id, tenant_id, "access", timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES), {"sv": int(session_version)})


def create_refresh_token(user_id: int, tenant_id: int, session_version: int = 0) -> str:
    """签发 refresh token。"""
    return create_token(user_id, tenant_id, "refresh", timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS), {"sv": int(session_version)})


def create_sso_state(tenant_id: int) -> str:
    """签发十分钟有效的 OIDC state。"""
    return create_token(0, tenant_id, "sso_state", timedelta(minutes=10))


def decode_token(token: str, expected_type: str = "access") -> dict:
    """验证 JWT 签名、有效期和 token 类型。"""
    payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("unexpected token type")
    return payload
