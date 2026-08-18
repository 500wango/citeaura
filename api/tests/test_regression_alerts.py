from api.adapters import engine as engine_adapter
from api.adapters import measurement, regression_alerts
from api.adapters.engine import geolib, with_tenant_context
from api.models import Membership, Project, Tenant, User
from api.tests.test_product_optimizations import _metrics


def test_regression_events_only_fire_on_noteworthy_drops(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    with with_tenant_context("tenant", "project"):
        directory = geolib.project_dir("project")
        geolib.write_json(directory / "metrics" / "2026-07-01.json", _metrics("2026-07-01", "v1", 0.30))
        geolib.write_json(directory / "metrics" / "2026-08-01.json", _metrics("2026-08-01", "v1", 0.10))
        events = measurement.regression_events("project")
        assert events[0]["kind"] == "overall"
        assert events[0]["delta_pp"] == -20.0
        engines = {item["engine_code"] for item in events if item["kind"] == "engine"}
        assert engines == {"provider_0", "provider_1"}

        geolib.write_json(directory / "metrics" / "2026-08-01.json", _metrics("2026-08-01", "v1", 0.31))
        assert measurement.regression_events("project") == []


def test_notify_if_needed_sends_once_and_skips_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    sent = []

    from api.db import SessionLocal, Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite:///{tmp_path / 'alerts.sqlite'}")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(regression_alerts, "SessionLocal", Session)
    monkeypatch.setattr(regression_alerts.config, "auth_smtp_configured", lambda: True)
    monkeypatch.setattr(regression_alerts.config, "public_base_url", lambda: "https://citeaura.test")
    monkeypatch.setattr(regression_alerts.notify, "send_product_email", lambda *args, **kwargs: sent.append(args))

    with Session() as db:
        tenant = Tenant(name="alerts", directory_slug="alerts", plan="pro")
        user = User(email="owner@example.com", password_hash="hash")
        db.add_all([tenant, user])
        db.flush()
        db.add(Membership(tenant_id=tenant.id, user_id=user.id, role="owner"))
        project = Project(tenant_id=tenant.id, slug="project", url="https://brand.example", market="global")
        db.add(project)
        db.commit()
        tenant_id = tenant.id

    with with_tenant_context("alerts", "project"):
        directory = geolib.project_dir("project")
        geolib.write_json(directory / "metrics" / "2026-07-01.json", _metrics("2026-07-01", "v1", 0.30))
        geolib.write_json(directory / "metrics" / "2026-08-01.json", _metrics("2026-08-01", "v1", 0.10))
        skipped = regression_alerts.notify_if_needed(tenant_id, "project", "sample")
        assert skipped["status"] == "skipped"

        with Session() as db:
            db.query(Project).one().alert_on_regression = True
            db.commit()

        first = regression_alerts.notify_if_needed(tenant_id, "project", "sample")
        second = regression_alerts.notify_if_needed(tenant_id, "project", "sample")
        assert first["status"] == "sent"
        assert first["recipients"] == 1
        assert second["reason"] == "already_sent"
        assert len(sent) == 1
        assert "mention-rate drop" in sent[0][1]
        assert "brand.example" in sent[0][2]
