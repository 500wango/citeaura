import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.adapters import engine as engine_adapter
from api.db import Base, get_db
from api.main import app
from api.models import Project


@pytest.fixture()
def ui_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    engine = create_engine(f"sqlite:///{tmp_path / 'ui.sqlite'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client, session_factory, tmp_path
    app.dependency_overrides.clear()


def test_ui_is_served_with_disvorai_brand_and_saas_adapter():
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert "DisvorAI" in response.text
    assert "GeoLook" not in response.text
    assert 'Geo<span style="color:var(--accent)">Look</span>' not in response.text
    assert "/api/v1/auth/login" in response.text
    assert "/api/v1/projects" in response.text
    assert "/api/v1/settings/keys" in response.text
    assert "disvorai_access_token" in response.text
    assert "job.status === 'queued' ? 'running'" in response.text
    assert "skip_llm:configuredKeyCount === 0" in response.text
    assert "document.querySelector('#ob-nosample')?.checked" in response.text
    assert "data.job.log_offset || requested" in response.text
    assert "/api/v1/projects/actions" in response.text
    assert "'/actions/' + encodeURIComponent(action)" in response.text
    assert "if (action === 'serve') action = 'sample'" not in response.text


def test_project_files_use_cookie_auth_and_remain_tenant_isolated(ui_client):
    client, session_factory, tmp_path = ui_client
    first = client.post(
        "/api/v1/auth/register",
        json={"email": "first@example.com", "password": "correct-horse-battery", "tenant_name": "tenant-a"},
    ).json()
    second = client.post(
        "/api/v1/auth/register",
        json={"email": "second@example.com", "password": "correct-horse-battery", "tenant_name": "tenant-b"},
    ).json()
    with session_factory() as db:
        db.add_all([
            Project(tenant_id=first["tenant"]["id"], slug="first-project", url="https://first.example", market="both"),
            Project(tenant_id=second["tenant"]["id"], slug="second-project", url="https://second.example", market="both"),
        ])
        db.commit()

    first_file = tmp_path / "work" / "tenant-a" / "first-project" / "delivery" / "2026-07-31" / "index.html"
    first_file.parent.mkdir(parents=True)
    first_file.write_text("first tenant delivery", "utf-8")
    second_file = tmp_path / "work" / "tenant-b" / "second-project" / "delivery" / "2026-07-31" / "index.html"
    second_file.parent.mkdir(parents=True)
    second_file.write_text("second tenant delivery", "utf-8")

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "first@example.com", "password": "correct-horse-battery"},
    )
    assert login.status_code == 200
    downloaded = client.get("/files/first-project/delivery/2026-07-31/index.html")
    assert downloaded.status_code == 200
    assert downloaded.text == "first tenant delivery"
    assert client.get("/files/second-project/delivery/2026-07-31/index.html").status_code == 404

    client.cookies.clear()
    assert client.get("/files/first-project/delivery/2026-07-31/index.html").status_code == 401
