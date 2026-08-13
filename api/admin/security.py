"""平台管理员会话安全。"""

from datetime import timedelta

from api.auth.security import create_token


ADMIN_COOKIE = "citeaura_admin_session"
ADMIN_SESSION_MINUTES = 30


def create_admin_token(admin):
    return create_token(
        admin.id,
        0,
        "admin_access",
        timedelta(minutes=ADMIN_SESSION_MINUTES),
        {"sv": int(admin.session_version), "role": admin.role},
    )
