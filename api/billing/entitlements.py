"""租户能力授权：以 features.yaml 为唯一真源。"""

from fastapi import HTTPException, status

from api.adapters.capabilities import feature_enabled
from api.models import Tenant


def tenant_plan(db, tenant_id):
    tenant = db.get(Tenant, tenant_id) if tenant_id is not None else None
    return (tenant.plan or "trial") if tenant is not None else "trial"


def tenant_entitlements(db, tenant_id):
    """返回当前套餐可用的功能 ID 集合。"""
    from api.adapters.capabilities import features

    plan = tenant_plan(db, tenant_id)
    return {
        item["id"] for item in features()
        if feature_enabled(item.get("id"), plan)
    }


def has_entitlement(db, tenant_id, feature_id):
    return feature_enabled(feature_id, tenant_plan(db, tenant_id))


def require_entitlement(db, tenant_id, feature_id):
    if has_entitlement(db, tenant_id, feature_id):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"error": "feature_not_entitled", "feature": feature_id},
    )
