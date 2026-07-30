"""计费用量 API。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.auth.deps import get_current_user
from api.billing.limits import usage
from api.db import get_db
from api.models import Tenant, User


router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


@router.get("/usage")
def billing_usage(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """返回当前租户试用/订阅用量。"""
    tenant = db.get(Tenant, current_user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "no_tenant_membership"})
    return usage(db, tenant)

