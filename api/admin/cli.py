"""平台管理员本机初始化命令。"""

import argparse
import getpass
import re

from api.auth.security import hash_password
from api.billing.plans import SUBSCRIBABLE_PLANS
from api.db import SessionLocal
from api.models import Membership, PlatformAdmin, Tenant, User


ROLES = ("support", "ops", "finance", "superadmin")


def _normalized_email(email):
    email = email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("invalid admin email")
    return email


def _validated_password(password):
    if len(password) < 12:
        raise ValueError("admin password must be at least 12 characters")
    return password


def _new_password():
    password = getpass.getpass("New admin password: ")
    confirmation = getpass.getpass("Confirm new admin password: ")
    if password != confirmation:
        raise ValueError("admin passwords do not match")
    return password


def create_admin(email, role, password=None):
    email = _normalized_email(email)
    password = getpass.getpass("Admin password: ") if password is None else password
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
    email = _normalized_email(email)
    password = _new_password() if password is None else password
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


def grant_plan(email, plan, tenant_id=None):
    """按账号所有权授予套餐权益，不生成支付记录。"""
    email = _normalized_email(email)
    plan = plan.strip().lower()
    if plan not in SUBSCRIBABLE_PLANS:
        raise ValueError("unsupported plan")
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).one_or_none()
        if user is None:
            raise ValueError("user does not exist")
        query = db.query(Tenant).join(Membership, Membership.tenant_id == Tenant.id).filter(
            Membership.user_id == user.id,
            Membership.role == "owner",
        )
        if tenant_id is not None:
            query = query.filter(Tenant.id == tenant_id)
        tenants = query.all()
        if not tenants:
            raise ValueError("owned workspace does not exist")
        if len(tenants) > 1:
            choices = ", ".join(f"{tenant.id}:{tenant.name}" for tenant in tenants)
            raise ValueError(f"multiple owned workspaces; pass --tenant-id ({choices})")
        tenant = tenants[0]
        previous = tenant.plan
        tenant.plan = plan
        tenant.trial_ends_at = None
        db.commit()
        return {"tenant_id": tenant.id, "tenant_name": tenant.name, "previous": previous, "plan": plan}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Manage CiteAura platform administrators")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("--email", required=True)
    create_parser.add_argument("--role", choices=ROLES, default="superadmin")
    reset_parser = subparsers.add_parser("reset-password")
    reset_parser.add_argument("--email", required=True)
    grant_parser = subparsers.add_parser("grant-plan")
    grant_parser.add_argument("--email", required=True)
    grant_parser.add_argument("--plan", choices=sorted(SUBSCRIBABLE_PLANS), required=True)
    grant_parser.add_argument("--tenant-id", type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            create_admin(args.email, args.role)
            message = "Platform administrator created."
        elif args.command == "reset-password":
            reset_admin_password(args.email)
            message = "Platform administrator password reset."
        else:
            result = grant_plan(args.email, args.plan, args.tenant_id)
            message = (
                f"Plan granted: {args.email}, workspace={result['tenant_name']} "
                f"({result['tenant_id']}), {result['previous']} -> {result['plan']}."
            )
    except ValueError as exc:
        parser.error(str(exc))
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
