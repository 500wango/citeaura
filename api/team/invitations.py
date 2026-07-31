"""团队邀请 token 的生成与校验。"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from api.models import TeamInvitation


INVITATION_TTL_DAYS = 7


def new_token():
    """生成只在邀请响应中出现一次的随机 token。"""
    return secrets.token_urlsafe(32)


def token_hash(token):
    """邀请 token 仅以 SHA-256 摘要入库。"""
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def expires_at():
    return datetime.now(timezone.utc) + timedelta(days=INVITATION_TTL_DAYS)


def invitation_for_token(db, token, for_update=False):
    token = str(token or "").strip()
    if not 20 <= len(token) <= 512:
        return None
    query = db.query(TeamInvitation).filter(TeamInvitation.token_hash == token_hash(token))
    if for_update:
        query = query.with_for_update()
    return query.first()


def is_expired(invitation):
    value = invitation.expires_at
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= datetime.now(timezone.utc)
