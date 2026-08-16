"""租户白标交付设置 API。"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.adapters import branding
from api.adapters.engine import with_tenant_context, with_tenant_read_context
from api.auth.deps import get_current_user, require_owner
from api.db import get_db
from api.models import Tenant, User


router = APIRouter(prefix="/api/v1/settings/delivery-branding", tags=["settings"])
WHITE_LABEL_PLANS = frozenset(("agency", "enterprise"))


class BrandingRequest(BaseModel):
    enabled: bool = False
    company_name: str = Field(default="", max_length=120)
    logo_data_url: str = Field(default="", max_length=750_000)
    accent_color: str = Field(default="#1F4E79", min_length=7, max_length=7)
    footer_text: str = Field(default="", max_length=240)


def _error(status_code, message):
    raise HTTPException(status_code=status_code, detail={"error": message})


def _tenant(db, user):
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None:
        _error(status.HTTP_403_FORBIDDEN, "no_tenant_membership")
    return tenant


def _load(tenant):
    with with_tenant_read_context(tenant, "branding"):
        return branding.load_branding()


def _response(tenant, user, value):
    available = tenant.plan in WHITE_LABEL_PLANS
    return {
        "available": available,
        "can_edit": available and getattr(user, "tenant_role", None) == "owner",
        "plan": tenant.plan,
        "branding": value,
    }


@router.get("")
def get_delivery_branding(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """读取当前租户的交付白标配置。"""
    tenant = _tenant(db, current_user)
    return _response(tenant, current_user, _load(tenant))


@router.put("")
def put_delivery_branding(
    payload: BrandingRequest,
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Agency/Enterprise owner 保存交付白标模板。"""
    tenant = _tenant(db, current_user)
    if tenant.plan not in WHITE_LABEL_PLANS:
        _error(status.HTTP_403_FORBIDDEN, "white_label_plan_required")
    try:
        with with_tenant_context(tenant.directory_slug, "branding"):
            value = branding.save_branding(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "invalid_delivery_branding", "detail": str(exc)},
        ) from exc
    return _response(tenant, current_user, value)


@router.delete("")
def delete_delivery_branding(
    current_user: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """移除当前租户白标设置；降级后仍允许清理。"""
    tenant = _tenant(db, current_user)
    with with_tenant_context(tenant.directory_slug, "branding"):
        value = branding.delete_branding()
    return _response(tenant, current_user, value)
