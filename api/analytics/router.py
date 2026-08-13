"""匿名落地页事件采集。"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from api import config
from api.country import request_country_code
from api.db import get_db
from api.models import ProductEvent
from api.product_events import record_product_event


router = APIRouter(prefix="/api/v1/events", tags=["analytics"])
VISITOR_COOKIE = "citeaura_visitor"


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
