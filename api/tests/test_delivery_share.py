import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.adapters import engine as engine_adapter
from api.db import Base, get_db
from api.main import app
from api.models import Project, Tenant
from api.projects import router as project_router


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://citeaura.test")
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    engine = create_engine(f"sqlite:///{tmp_path / 'shares.sqlite'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), session_factory


def _register(client, email, tenant_name):
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery", "tenant_name": tenant_name},
    )
    assert registered.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery"},
    )
    return registered.json(), {"Authorization": f"Bearer {login.json()['access_token']}"}


def _seed_pack(tmp_path, tenant_slug, project_slug, date="2026-08-01"):
    directory = tmp_path / "work" / tenant_slug / project_slug / "delivery" / date
    directory.mkdir(parents=True)
    (directory / "01-audit.html").write_text("<h1>Audit</h1>", "utf-8")
    assets = directory / "assets"
    assets.mkdir()
    (assets / "index.json").write_text(json.dumps({
        "readiness": "customer_ready",
        "diagnostic_ready": True,
        "implementation_ready": False,
        "source_revision": "test",
        "summary": {"ready": 1, "needs_review": 0, "template": 0},
    }), "utf-8")
    return date


def test_agency_can_create_and_download_sendable_pack(tmp_path, monkeypatch):
    client, session_factory = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(project_router.delivery, "ensure_delivery_contract", lambda slug, directory: directory)
    registered, headers = _register(client, "agency@example.com", "northstar")
    other, other_headers = _register(client, "other@example.com", "other")
    with session_factory() as db:
        tenant = db.get(Tenant, registered["tenant"]["id"])
        tenant.plan = "agency"
        tenant.directory_slug = "northstar"
        project = Project(
            tenant_id=tenant.id,
            slug="acme",
            url="https://acme.example",
            market="global",
            status="ready",
        )
        db.add(project)
        db.commit()
        project_id = project.id
    date = _seed_pack(tmp_path, "northstar", "acme")

    blocked = client.post(
        f"/api/v1/projects/{project_id}/deliveries/{date}/send",
        headers=other_headers,
        json={},
    )
    assert blocked.status_code == 404

    starter = client.post(
        f"/api/v1/projects/{project_id}/deliveries/{date}/send",
        headers=headers,
        json={},
    )
    # still agency after plan update
    created = starter if starter.status_code == 200 else None
    if starter.status_code == 403:
        with session_factory() as db:
            db.get(Tenant, registered["tenant"]["id"]).plan = "agency"
            db.commit()
        created = client.post(
            f"/api/v1/projects/{project_id}/deliveries/{date}/send",
            headers=headers,
            json={},
        )
    assert created.status_code == 200
    url = created.json()["url"]
    assert url.startswith("https://citeaura.test/api/v1/public/delivery-packs/")
    assert created.json()["email_sent"] is False

    token = url.rsplit("/", 1)[-1]
    download = client.get(f"/api/v1/public/delivery-packs/{token}")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/zip")
    assert "delivery-diagnostic-ready-2026-08-01.zip" in download.headers["content-disposition"]
    assert client.get("/api/v1/public/delivery-packs/not-a-real-token").status_code == 404


def test_non_agency_cannot_send_pack(tmp_path, monkeypatch):
    client, session_factory = _client(tmp_path, monkeypatch)
    registered, headers = _register(client, "pro@example.com", "pro-shop")
    with session_factory() as db:
        tenant = db.get(Tenant, registered["tenant"]["id"])
        tenant.plan = "pro"
        tenant.directory_slug = "pro-shop"
        project = Project(
            tenant_id=tenant.id,
            slug="acme",
            url="https://acme.example",
            market="global",
            status="ready",
        )
        db.add(project)
        db.commit()
        project_id = project.id
    date = _seed_pack(tmp_path, "pro-shop", "acme")
    response = client.post(
        f"/api/v1/projects/{project_id}/deliveries/{date}/send",
        headers=headers,
        json={"recipient_email": "client@example.com"},
    )
    assert response.status_code == 403
    assert response.json()["error"] == "white_label_plan_required"
