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


def test_spa_is_served_with_citeaura_shell():
    response = TestClient(app).get("/app")

    assert response.status_code == 200
    assert "CiteAura" in response.text
    assert "GeoLook" not in response.text
    assert 'id="app"' in response.text
    assert '<script type="module" src="/app/app.js">' in response.text
    assert "/site-assets/styles/tokens.css" in response.text
    assert "/site-assets/styles/base.css" in response.text
    assert "/site-assets/styles/components.css" in response.text
    assert "/site-assets/styles/app.css" in response.text


def test_spa_static_modules_are_served():
    client = TestClient(app)
    for path in (
        "/app/app.js",
        "/app/api.js",
        "/app/i18n.js",
        "/app/views/overview.js",
        "/app/views/engines.js",
        "/app/views/plan.js",
        "/app/views/report.js",
        "/app/views/onboarding.js",
        "/app/components/toast.js",
        "/app/components/modal.js",
        "/app/components/badge.js",
        "/app/components/kpi.js",
        "/app/components/table.js",
        "/app/components/tabs.js",
    ):
        response = client.get(path)
        assert response.status_code == 200, f"Failed to serve {path}"
        assert "javascript" in response.headers["content-type"].lower() or "text/" in response.headers["content-type"].lower()


def test_api_js_covers_all_core_endpoints():
    response = TestClient(app).get("/app/api.js")
    assert response.status_code == 200
    text = response.text
    assert "/api/v1/auth/login" in text
    assert "/api/v1/auth/refresh" in text
    assert "/api/v1/auth/logout" in text
    assert "/api/v1/auth/password/forgot" in text
    assert "/api/v1/auth/password/reset" in text
    assert "/api/v1/projects" in text
    assert "/api/v1/settings/keys" in text


def test_ui_compatibility_route_remains_available():
    response = TestClient(app).get("/ui")

    assert response.status_code == 200
    assert "CiteAura" in response.text
    assert '<script type="module" src="/app/app.js">' in response.text


@pytest.mark.parametrize(
    "name",
    ["layout-dashboard", "radar", "scan-search", "list-checks", "package-check", "settings-2", "menu", "x", "plus"],
)
def test_admin_navigation_icons_are_served_locally(name):
    response = TestClient(app).get(f"/site-assets/icons/{name}.svg")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert "lucide-static" in response.text


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
    assert "sandbox" in downloaded.headers["content-security-policy"]
    assert "script-src" not in downloaded.headers["content-security-policy"]
    assert client.get("/files/second-project/delivery/2026-07-31/index.html").status_code == 404

    client.cookies.clear()
    assert client.get("/files/first-project/delivery/2026-07-31/index.html").status_code == 401
