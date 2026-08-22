"""匿名落地页事件采集。"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from api import config
from api.auth.security import ACCESS_TOKEN_COOKIE, decode_token
from api.country import request_country_code
from api.db import get_db
from api.models import ProductEvent
from api.product_events import record_product_event


router = APIRouter(prefix="/api/v1/events", tags=["analytics"])
VISITOR_COOKIE = "citeaura_visitor"
PUBLIC_EVENT_NAMES = frozenset({
    "landing_cta_clicked",
    "sample_report_viewed",
    "public_audit_started",
    "public_audit_completed",
    "audit_only_selected",
    "full_baseline_selected",
    "report_viewed",
    "ticket_opened",
    "ticket_updated",
    "verify_started",
    "verify_completed",
    "delivery_built",
    "delivery_downloaded",
    "delivery_shared",
    "signup_started",
    "checkout_started",
    "checkout_succeeded",
})


class ProductEventRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    properties: dict = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str):
        if value not in PUBLIC_EVENT_NAMES:
            raise ValueError("unsupported public event")
        return value

    @field_validator("properties")
    @classmethod
    def validate_properties(cls, value: dict):
        if len(value) > 12:
            raise ValueError("too many event properties")
        clean = {}
        for key, item in value.items():
            key = str(key)
            if len(key) > 48:
                continue
            if isinstance(item, (str, int, float, bool)) or item is None:
                clean[key] = str(item)[:256] if isinstance(item, str) else item
        return clean


def visitor_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def request_visitor(request):
    value = request.cookies.get(VISITOR_COOKIE, "")
    if len(value) < 20 or len(value) > 128:
        return None
    return visitor_hash(value)


@router.post("/landing")
def landing_view(request: Request, response: Response, db: Session = Depends(get_db)):
    """按第一方匿名访客每日记录一次落地页访问。"""
    raw_visitor = request.cookies.get(VISITOR_COOKIE)
    if not raw_visitor or len(raw_visitor) < 20 or len(raw_visitor) > 128:
        raw_visitor = secrets.token_urlsafe(24)
        response.set_cookie(
            VISITOR_COOKIE,
            raw_visitor,
            max_age=365 * 86400,
            httponly=True,
            secure=config.session_cookie_secure(),
            samesite="lax",
        )
    anonymous_id = visitor_hash(raw_visitor)
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    exists = db.query(ProductEvent.id).filter(
        ProductEvent.name == "landing_view",
        ProductEvent.anonymous_id == anonymous_id,
        ProductEvent.created_at >= cutoff,
    ).first()
    if exists is None:
        record_product_event(
            db,
            "landing_view",
            anonymous_id=anonymous_id,
            country_code=request_country_code(request),
        )
        db.commit()
    return {"recorded": exists is None}


@router.post("/product", status_code=status.HTTP_202_ACCEPTED)
def product_event(payload: ProductEventRequest, request: Request, db: Session = Depends(get_db)):
    """接收匿名增长事件；只允许公开事件白名单，避免把按钮日志变成任意写入。"""
    tenant_id = None
    user_id = None
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if token:
        try:
            claims = decode_token(token, expected_type="access")
            tenant_id = int(claims["tenant_id"])
            user_id = int(claims["sub"])
        except (KeyError, TypeError, ValueError, RuntimeError, jwt.PyJWTError):
            tenant_id = None
            user_id = None
    record_product_event(
        db,
        payload.name,
        tenant_id=tenant_id,
        user_id=user_id,
        anonymous_id=request_visitor(request),
        country_code=request_country_code(request),
        properties=payload.properties,
    )
    db.commit()
    return {"accepted": True}
