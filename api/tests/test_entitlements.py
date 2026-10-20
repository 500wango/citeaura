"""套餐能力授权测试。"""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.billing.entitlements import (
    has_entitlement, require_entitlement, tenant_entitlements, tenant_plan,
)
from api.db import Base
from api.models import Tenant


@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'entitlements.sqlite'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        yield session


def _tenant(db, plan):
    tenant = Tenant(name=f"tenant-{plan}", directory_slug=f"tenant-{plan}", plan=plan)
    db.add(tenant)
    db.commit()
    return tenant


def test_plan_entitlements_follow_feature_catalog(db_session):
    trial = _tenant(db_session, "trial")
    starter = _tenant(db_session, "starter")
    pro = _tenant(db_session, "pro")
    agency = _tenant(db_session, "agency")

    assert tenant_plan(db_session, trial.id) == "trial"
    assert "effect_verification" in tenant_entitlements(db_session, trial.id)
    assert "scheduled_monitoring" not in tenant_entitlements(db_session, trial.id)

    assert has_entitlement(db_session, starter.id, "scheduled_monitoring") is False
    assert has_entitlement(db_session, pro.id, "scheduled_monitoring") is True
    assert has_entitlement(db_session, pro.id, "regression_alerts") is True
    assert has_entitlement(db_session, pro.id, "white_label_delivery") is False
    assert has_entitlement(db_session, agency.id, "white_label_delivery") is True


def test_removed_and_internal_features_are_never_entitled(db_session):
    agency = _tenant(db_session, "agency")
    assert has_entitlement(db_session, agency.id, "enterprise_sso") is False
    assert has_entitlement(db_session, agency.id, "audit_event_log") is False


def test_require_entitlement_returns_stable_error(db_session):
    starter = _tenant(db_session, "starter")
    with pytest.raises(HTTPException) as excinfo:
        require_entitlement(db_session, starter.id, "white_label_delivery")
    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == {
        "error": "feature_not_entitled", "feature": "white_label_delivery",
    }
