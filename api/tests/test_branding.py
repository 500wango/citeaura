import base64

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.adapters import branding
from api.adapters import engine as engine_adapter
from api.adapters.delivery import ensure_delivery_contract
from api.db import Base, get_db
from api.main import app
from api.models import Tenant


@pytest.fixture()
def branding_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    engine = create_engine(f"sqlite:///{tmp_path / 'branding.sqlite'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client, session_factory, tmp_path
    app.dependency_overrides.clear()


def _register(client, email, tenant_name=None, invitation_token=None):
    payload = {"email": email, "password": "correct-horse-battery", "tenant_name": tenant_name}
    if invitation_token:
        payload["invitation_token"] = invitation_token
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery"},
    )
    assert login.status_code == 200
    return response.json(), {"Authorization": f"Bearer {login.json()['access_token']}"}


def _logo():
    raw = b"\x89PNG\r\n\x1a\n" + b"delivery-logo"
    return "data:image/png;base64," + base64.b64encode(raw).decode()


def test_branding_api_enforces_plan_owner_and_tenant_isolation(branding_client):
    client, session_factory, tmp_path = branding_client
    first, owner_headers = _register(client, "owner@example.com", "agency-one")

    initial = client.get("/api/v1/settings/delivery-branding", headers=owner_headers)
    assert initial.status_code == 200
    assert initial.json()["available"] is False
    assert initial.json()["branding"]["enabled"] is False
    blocked = client.put(
        "/api/v1/settings/delivery-branding",
        headers=owner_headers,
        json={"enabled": True, "company_name": "Northstar Studio"},
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"] == "white_label_plan_required"

    with session_factory() as db:
        db.get(Tenant, first["tenant"]["id"]).plan = "agency"
        db.commit()

    saved = client.put(
        "/api/v1/settings/delivery-branding",
        headers=owner_headers,
        json={
            "enabled": True,
            "company_name": "Northstar Studio",
            "logo_data_url": _logo(),
            "accent_color": "#0f766e",
            "footer_text": "Prepared for the client",
        },
    )
    assert saved.status_code == 200
    assert saved.json()["can_edit"] is True
    assert saved.json()["branding"]["accent_color"] == "#0F766E"
    assert (tmp_path / "work" / "agency-one" / branding.BRANDING_FILENAME).is_file()

    invitation = client.post(
        "/api/v1/team/invitations",
        headers=owner_headers,
        json={"email": "editor@example.com", "role": "editor"},
    ).json()
    _, editor_headers = _register(
        client,
        "editor@example.com",
        invitation_token=invitation["token"],
    )
    editor_view = client.get("/api/v1/settings/delivery-branding", headers=editor_headers)
    assert editor_view.status_code == 200
    assert editor_view.json()["can_edit"] is False
    assert editor_view.json()["branding"]["company_name"] == "Northstar Studio"
    assert client.put(
        "/api/v1/settings/delivery-branding",
        headers=editor_headers,
        json={"enabled": False},
    ).status_code == 403

    _, other_headers = _register(client, "other@example.com", "agency-two")
    other = client.get("/api/v1/settings/delivery-branding", headers=other_headers)
    assert other.status_code == 200
    assert other.json()["branding"]["company_name"] == ""

    deleted = client.delete("/api/v1/settings/delivery-branding", headers=owner_headers)
    assert deleted.status_code == 200
    assert deleted.json()["branding"]["enabled"] is False
    assert not (tmp_path / "work" / "agency-one" / branding.BRANDING_FILENAME).exists()


def test_branding_api_rejects_invalid_enabled_config(branding_client):
    client, session_factory, _ = branding_client
    registered, headers = _register(client, "owner@example.com", "agency")
    with session_factory() as db:
        db.get(Tenant, registered["tenant"]["id"]).plan = "agency"
        db.commit()

    missing_name = client.put(
        "/api/v1/settings/delivery-branding",
        headers=headers,
        json={"enabled": True, "company_name": ""},
    )
    assert missing_name.status_code == 422
    assert missing_name.json()["error"] == "invalid_delivery_branding"
    invalid_logo = client.put(
        "/api/v1/settings/delivery-branding",
        headers=headers,
        json={
            "enabled": True,
            "company_name": "Agency",
            "logo_data_url": "data:image/png;base64," + base64.b64encode(b"not-a-png").decode(),
        },
    )
    assert invalid_logo.status_code == 422


def test_delivery_contract_applies_idempotent_print_branding(tmp_path, monkeypatch):
    tenant_root = tmp_path / "tenant"
    project = tenant_root / "example"
    output = project / "delivery" / "2026-07-31"
    output.mkdir(parents=True)
    document = "<!doctype html><html><head><title>Report</title></head><body><main>Content</main></body></html>"
    for number, name in (("01", "诊断报告"), ("03", "工单表"), ("04", "验收表"), ("06", "建设地图")):
        (output / f"{number}-{name}.html").write_text(document, "utf-8")
    (output / "index.html").write_text(document, "utf-8")
    plan = project / "deliverables" / "2-GEO优化方案.md"
    plan.parent.mkdir()
    plan.write_text("# Execution plan\n", "utf-8")

    monkeypatch.setattr(branding.geolib, "WORK", tenant_root)
    monkeypatch.setattr("api.adapters.delivery.geolib.project_dir", lambda slug: project)
    monkeypatch.setattr("api.adapters.delivery.geolib.today", lambda: "2026-07-31")
    branding.save_branding({
        "enabled": True,
        "company_name": "Northstar <Studio>",
        "logo_data_url": _logo(),
        "accent_color": "#0F766E",
        "footer_text": "Prepared & reviewed",
    })

    ensure_delivery_contract("example", output)
    ensure_delivery_contract("example", output)

    branded = (output / "01-Audit-Report.html").read_text("utf-8")
    assert branded.count(branding.STYLE_START) == 1
    assert branded.count(branding.BODY_START) == 1
    assert "Northstar &lt;Studio&gt;" in branded
    assert "Prepared &amp; reviewed" in branded
    assert "@page{margin:22mm 14mm 18mm}" in branded
    assert "position:fixed;top:-16mm" in branded
    assert ".delivery-branding-footer{display:none" in branded
    assert ".delivery-branding-footer{display:block;position:fixed" in branded
    assert _logo() in branded
    assert branding.BODY_START in (output / "index.html").read_text("utf-8")

    branding.save_branding({"enabled": False})
    ensure_delivery_contract("example", output)
    unbranded = (output / "01-Audit-Report.html").read_text("utf-8")
    assert branding.STYLE_START not in unbranded
    assert branding.BODY_START not in unbranded
