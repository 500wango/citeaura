"""团队成员、邀请和角色管理 API。"""

import re
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from api.auth.deps import get_current_user, require_owner
from api.auth.router import token_response
from api.db import get_db
from api.models import Membership, TeamInvitation, Tenant, User
from api.team.invitations import expires_at, invitation_for_token, is_expired, new_token, token_hash


router = APIRouter(prefix="/api/v1/team", tags=["team"])
ROLES = ("owner", "editor", "viewer")


class InviteRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: str = "viewer"

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("invalid email")
        return value

    @field_validator("role")
    @classmethod
    def validate_role(cls, value):
        value = value.strip().lower()
        if value not in ROLES:
            raise ValueError("invalid team role")
        return value


class RoleRequest(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, value):
        value = value.strip().lower()
        if value not in ROLES:
            raise ValueError("invalid team role")
        return value


class AcceptRequest(BaseModel):
    token: str = Field(min_length=20, max_length=512)


def _error(status_code, message):
    raise HTTPException(status_code=status_code, detail={"error": message})


def _tenant(db, user):
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None:
        _error(status.HTTP_403_FORBIDDEN, "no_tenant_membership")
    return tenant


def _member_payload(membership, user):
    return {
        "user_id": user.id,
        "email": user.email,
        "role": membership.role,
        "is_current_user": False,
    }


def _invitation_payload(invitation):
    return {
        "id": invitation.id,
        "email": invitation.email,
        "role": invitation.role,
        "expires_at": invitation.expires_at,
        "accepted_at": invitation.accepted_at,
        "created_at": invitation.created_at,
        "status": "accepted" if invitation.accepted_at else ("expired" if is_expired(invitation) else "pending"),
    }


def _owners_for_update(db, tenant_id):
    return db.query(Membership).filter(
        Membership.tenant_id == tenant_id,
        Membership.role == "owner",
    ).order_by(Membership.user_id).with_for_update().all()


def _membership_for_update(db, tenant_id, user_id):
    return db.query(Membership).filter(
        Membership.tenant_id == tenant_id,
        Membership.user_id == user_id,
    ).with_for_update().first()


@router.get("/members")
def list_members(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """列出当前工作区成员和当前用户角色。"""
    tenant = _tenant(db, current_user)
    rows = (
        db.query(Membership, User)
        .join(User, User.id == Membership.user_id)
        .filter(Membership.tenant_id == tenant.id)
        .order_by(User.email)
        .all()
    )
    members = []
    for membership, user in rows:
        item = _member_payload(membership, user)
        item["is_current_user"] = user.id == current_user.id
        members.append(item)
    return {"tenant": {"id": tenant.id, "name": tenant.name}, "current_role": current_user.tenant_role, "members": members}


@router.get("/invitations")
def list_invitations(current_user: User = Depends(require_owner), db: Session = Depends(get_db)):
    """owner 查看邀请状态，响应不包含原始 token。"""
    tenant = _tenant(db, current_user)
    rows = (
        db.query(TeamInvitation)
        .filter(TeamInvitation.tenant_id == tenant.id)
        .order_by(TeamInvitation.id.desc())
        .limit(100)
        .all()
    )
    return {"invitations": [_invitation_payload(row) for row in rows]}


@router.post("/invitations", status_code=status.HTTP_201_CREATED)
def create_invitation(
    payload: InviteRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """创建或轮换一次性邀请链接。"""
    tenant = _tenant(db, current_user)
    existing_user = db.query(User).filter(User.email == payload.email).first()
    if existing_user and db.get(Membership, {"tenant_id": tenant.id, "user_id": existing_user.id}):
        _error(status.HTTP_409_CONFLICT, "already_team_member")

    invitation = (
        db.query(TeamInvitation)
        .filter(
            TeamInvitation.tenant_id == tenant.id,
            TeamInvitation.email == payload.email,
            TeamInvitation.accepted_at.is_(None),
        )
        .order_by(TeamInvitation.id.desc())
        .with_for_update()
        .first()
    )
    token = new_token()
    if invitation is None:
        invitation = TeamInvitation(
            tenant_id=tenant.id,
            email=payload.email,
            role=payload.role,
            token_hash=token_hash(token),
            invited_by_user_id=current_user.id,
            expires_at=expires_at(),
        )
        db.add(invitation)
    else:
        invitation.role = payload.role
        invitation.token_hash = token_hash(token)
        invitation.invited_by_user_id = current_user.id
        invitation.expires_at = expires_at()
    db.commit()
    db.refresh(invitation)
    return {
        "invitation": _invitation_payload(invitation),
        "token": token,
        "invite_url": f"/app/#/invite?token={quote(token)}",
    }


@router.delete("/invitations/{invitation_id}")
def revoke_invitation(
    invitation_id: int,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """撤销未接受的邀请。"""
    tenant = _tenant(db, current_user)
    invitation = db.query(TeamInvitation).filter(
        TeamInvitation.id == invitation_id,
        TeamInvitation.tenant_id == tenant.id,
        TeamInvitation.accepted_at.is_(None),
    ).first()
    if invitation is None:
        _error(status.HTTP_404_NOT_FOUND, "invitation_not_found")
    db.delete(invitation)
    db.commit()
    return {"deleted": True, "invitation_id": invitation_id}


@router.patch("/members/{user_id}")
def update_member_role(
    user_id: int,
    payload: RoleRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """修改成员角色，但始终保留至少一个 owner。"""
    tenant = _tenant(db, current_user)
    owners = _owners_for_update(db, tenant.id)
    membership = _membership_for_update(db, tenant.id, user_id)
    if membership is None:
        _error(status.HTTP_404_NOT_FOUND, "team_member_not_found")
    if membership.role == "owner" and payload.role != "owner" and len(owners) <= 1:
        _error(status.HTTP_409_CONFLICT, "last_owner_required")
    membership.role = payload.role
    db.commit()
    return {"member": {"user_id": user_id, "role": membership.role}}


@router.delete("/members/{user_id}")
def remove_member(
    user_id: int,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """移除成员，但禁止删除唯一 owner。"""
    tenant = _tenant(db, current_user)
    owners = _owners_for_update(db, tenant.id)
    membership = _membership_for_update(db, tenant.id, user_id)
    if membership is None:
        _error(status.HTTP_404_NOT_FOUND, "team_member_not_found")
    if membership.role == "owner" and len(owners) <= 1:
        _error(status.HTTP_409_CONFLICT, "last_owner_required")
    db.delete(membership)
    db.commit()
    return {"deleted": True, "user_id": user_id}


@router.get("/invitations/preview/{token}")
def invitation_preview(token: str, db: Session = Depends(get_db)):
    """邀请登录页读取工作区、邮箱和有效期。"""
    invitation = invitation_for_token(db, token)
    if invitation is None or invitation.accepted_at is not None or is_expired(invitation):
        _error(status.HTTP_404_NOT_FOUND, "invitation_not_found")
    tenant = db.get(Tenant, invitation.tenant_id)
    return {
        "tenant": {"id": tenant.id, "name": tenant.name},
        "email": invitation.email,
        "role": invitation.role,
        "expires_at": invitation.expires_at,
        "accepted": invitation.accepted_at is not None,
    }


@router.post("/invitations/accept")
def accept_invitation(
    request: Request,
    payload: AcceptRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """已有账号接受邀请，并签发目标工作区 token。"""
    invitation = invitation_for_token(db, payload.token, for_update=True)
    if invitation is None:
        _error(status.HTTP_404_NOT_FOUND, "invitation_not_found")
    if invitation.email != current_user.email:
        _error(status.HTTP_403_FORBIDDEN, "invitation_email_mismatch")
    if is_expired(invitation):
        _error(status.HTTP_410_GONE, "invitation_expired")
    membership = db.get(Membership, {"tenant_id": invitation.tenant_id, "user_id": current_user.id})
    if invitation.accepted_at is not None:
        if membership is None:
            _error(status.HTTP_404_NOT_FOUND, "invitation_not_found")
        _error(status.HTTP_409_CONFLICT, "invitation_already_accepted")
    if membership is None:
        membership = Membership(
            tenant_id=invitation.tenant_id,
            user_id=current_user.id,
            role=invitation.role,
        )
        db.add(membership)
    invitation.accepted_at = datetime.now(timezone.utc)
    db.commit()
    return token_response(
        response, current_user.id, invitation.tenant_id, db,
        expose_tokens=request.headers.get("X-CiteAura-Session") != "cookie",
    )
