"""密码哈希和 JWT 安全工具。"""

import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from api import config


JWT_ALGORITHM = "HS256"
JWT_AUDIENCE = "citeaura-api"
JWT_ISSUER = "citeaura"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 30
ACCESS_TOKEN_COOKIE = "citeaura_access_token"
REFRESH_TOKEN_COOKIE = "citeaura_refresh_token"
DUMMY_PASSWORD_HASH = "$2b$12$H1jR9wXl1wZzZzuUggIWKOCY0KKHBi0Rh.AyIyGIltOPbbIf5wm4."
REQUIRED_CLAIMS = ("exp", "iat", "sub", "type")
# 平台管理员令牌与租户会话必须使用不同的签名密钥：两者混用意味着一次
# JWT_SECRET 泄露就能铸出 admin_access。
ADMIN_TOKEN_TYPES = frozenset(("admin_access", "admin_refresh"))


def _jwt_secret():
    """读取 JWT 密钥；生产环境必须显式配置。"""
    secret = config.jwt_secret()
    if not config.jwt_secret_valid(secret):
        raise RuntimeError("JWT_SECRET must be a non-placeholder value of at least 32 characters")
    return secret


def _signing_key(token_type):
    base = _jwt_secret()
    if token_type in ADMIN_TOKEN_TYPES:
        return hmac.new(base.encode("utf-8"), b"citeaura:admin", hashlib.sha256).hexdigest()
    return base


PASSWORD_HASH_PREFIX = "sha256$"


def _password_digest(password: str) -> bytes:
    """先把任意长度密码压成固定 44 字节，绕开 bcrypt 的 72 字节上限。"""
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def hash_password(password: str) -> str:
    """使用 bcrypt 哈希密码。"""
    digest = _password_digest(password)
    return PASSWORD_HASH_PREFIX + bcrypt.hashpw(digest, bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """验证明文密码是否匹配 bcrypt 哈希。"""
    try:
        if password_hash.startswith(PASSWORD_HASH_PREFIX):
            return bcrypt.checkpw(_password_digest(password), password_hash[len(PASSWORD_HASH_PREFIX):].encode("ascii"))
        # 兼容历史哈希：bcrypt 只使用前 72 字节，旧账号仍可登录，
        # 下次设置密码时会升级为带前缀的新格式。
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
        "aud": JWT_AUDIENCE,
        "iss": JWT_ISSUER,
    }
    payload.update(extra_claims or {})
    return jwt.encode(payload, _signing_key(token_type), algorithm=JWT_ALGORITHM)


def create_access_token(
    user_id: int,
    tenant_id: int,
    session_version: int = 0,
) -> str:
    """签发 access token。"""
    return create_token(
        user_id, tenant_id, "access",
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES), {"sv": int(session_version)},
    )


def create_refresh_token(
    user_id: int,
    tenant_id: int,
    session_version: int = 0,
    family_id: str | None = None,
    token_id: str | None = None,
) -> str:
    """签发 refresh token。"""
    claims = {"sv": int(session_version)}
    if family_id:
        claims["fid"] = family_id
    if token_id:
        claims["jti"] = token_id
    return create_token(user_id, tenant_id, "refresh", timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS), claims)


def decode_token(token: str, expected_type: str = "access") -> dict:
    """验证 JWT 签名、有效期、受众和 token 类型。"""
    payload = jwt.decode(
        token,
        _signing_key(expected_type),
        algorithms=[JWT_ALGORITHM],
        audience=JWT_AUDIENCE,
        issuer=JWT_ISSUER,
        options={"require": list(REQUIRED_CLAIMS)},
    )
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("unexpected token type")
    return payload
