"""平台管理员本机初始化命令。"""

import argparse
import getpass
import re

from api.auth.security import hash_password
from api.db import SessionLocal
from api.models import PlatformAdmin


ROLES = ("support", "ops", "finance", "superadmin")


def _validated_password(password):
    if len(password) < 12:
        raise ValueError("admin password must be at least 12 characters")
    return password


def create_admin(email, role, password=None):
    email = email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("invalid admin email")
    password = password or getpass.getpass("Admin password: ")
    _validated_password(password)
    if password and password == email:
        raise ValueError("admin password must not match email")
    with SessionLocal() as db:
        if db.query(PlatformAdmin.id).filter(PlatformAdmin.email == email).first():
            raise ValueError("admin already exists")
        admin = PlatformAdmin(
            email=email,
            password_hash=hash_password(password),
            role=role,
        )
        db.add(admin)
        db.commit()


def reset_admin_password(email, password=None):
    """重置平台管理员密码，并使已有后台会话失效。"""
    email = email.strip().lower()
    password = password or getpass.getpass("New admin password: ")
    _validated_password(password)
    if password == email:
        raise ValueError("admin password must not match email")
    with SessionLocal() as db:
        admin = db.query(PlatformAdmin).filter(PlatformAdmin.email == email).first()
        if admin is None:
            raise ValueError("admin does not exist")
        admin.password_hash = hash_password(password)
        admin.session_version += 1
        db.commit()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Manage CiteAura platform administrators")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("--email", required=True)
    create_parser.add_argument("--role", choices=ROLES, default="superadmin")
    reset_parser = subparsers.add_parser("reset-password")
    reset_parser.add_argument("--email", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            create_admin(args.email, args.role)
            message = "Platform administrator created."
        else:
            reset_admin_password(args.email)
            message = "Platform administrator password reset."
    except ValueError as exc:
        parser.error(str(exc))
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
