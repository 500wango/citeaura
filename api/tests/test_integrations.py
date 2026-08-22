import hashlib
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.db import Base, get_db
from api.main import app
from api.models import Project, Tenant, User
from api.projects import router as project_router


def _fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "integration-test-secret-that-is-long-enough-32")
    engine = create_engine(f"sqlite:///{tmp_path / 'integrations.sqlite'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), sessions


def test_api_token_is_one_time_and_mcp_is_read_only(tmp_path, monkeypatch):
    client, sessions = _fixture(tmp_path, monkeypatch)
    try:
        registered = client.post("/api/v1/auth/register", json={
            "email": "integrations@example.com",
            "password": "correct-horse-battery",
        })
        assert registered.status_code == 201
        jwt_token = client.post("/api/v1/auth/login", json={
            "email": "integrations@example.com",
            "password": "correct-horse-battery",
        }).json()["access_token"]
        jwt_headers = {"Authorization": f"Bearer {jwt_token}"}
        created = client.post("/api/v1/settings/api-tokens", headers=jwt_headers, json={"name": "MCP read"})
        assert created.status_code == 201
        raw = created.json()["token"]
        assert raw.startswith("ca_")
        assert raw not in client.get("/api/v1/settings/api-tokens", headers=jwt_headers).text
        with sessions() as db:
            row = db.query(User).filter(User.email == "integrations@example.com").one()
            token_row = row.memberships[0].tenant.api_access_tokens[0]
            assert token_row.token_hash == hashlib.sha256(raw.encode()).hexdigest()
            assert raw not in token_row.token_hash

        api_headers = {"Authorization": f"Bearer {raw}"}
        projects = client.get("/api/v1/public-api/projects", headers=api_headers)
        assert projects.status_code == 200
        assert projects.json() == {"projects": []}
        listed = client.post("/api/v1/mcp", headers=api_headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert listed.status_code == 200
        assert {tool["name"] for tool in listed.json()["result"]["tools"]} >= {"list_projects", "get_visibility_report", "get_prompt_research"}

        token_id = created.json()["api_token"]["id"]
        assert client.delete(f"/api/v1/settings/api-tokens/{token_id}", headers=jwt_headers).status_code == 200
        assert client.get("/api/v1/public-api/projects", headers=api_headers).status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_public_api_report_and_csv_are_tenant_scoped(tmp_path, monkeypatch):
    client, sessions = _fixture(tmp_path, monkeypatch)
    try:
        registered = client.post("/api/v1/auth/register", json={
            "email": "report-api@example.com",
            "password": "correct-horse-battery",
        })
        jwt_token = client.post("/api/v1/auth/login", json={
            "email": "report-api@example.com",
            "password": "correct-horse-battery",
        }).json()["access_token"]
        jwt_headers = {"Authorization": f"Bearer {jwt_token}"}
        with sessions() as db:
            tenant = db.query(Tenant).filter(Tenant.id == registered.json()["tenant"]["id"]).one()
            project = Project(tenant_id=tenant.id, slug="report-example", url="https://report.example", status="ready")
            db.add(project)
            db.flush()
            row, raw = __import__("api.auth.api_tokens", fromlist=["issue"]).issue(db, tenant, "report")
            db.commit()
            project_id = project.id

        monkeypatch.setattr(project_router, "_project_report_payload", lambda db, tenant, project: {
            "report": {"date": "2026-08-23", "engines": [{
                "provider_name": "OpenAI", "model_id": "gpt-test", "sampling_mode": "API·联网检索",
                "sample_count": 3, "mention_rate": 0.5, "mention_interval": {"low": 0.2, "high": 0.8},
                "median_rank": 2, "citation_share": 0.4,
            }], "channels": [{"domain": "report.example", "count": 2, "question_count": 1, "engines": ["OpenAI"]}]},
            "date": "2026-08-23", "sample_artifact": "sample-test", "report_quality": {},
        })
        api_headers = {"Authorization": f"Bearer {raw}"}
        report = client.get(f"/api/v1/public-api/projects/{project_id}/report", headers=api_headers)
        assert report.status_code == 200
        assert report.json()["report"]["engines"][0]["provider_name"] == "OpenAI"
        csv = client.get(f"/api/v1/public-api/projects/{project_id}/report.csv", headers=api_headers)
        assert csv.status_code == 200
        assert "report.example" in csv.text
        assert "API·联网检索" in csv.text
        assert csv.headers["content-disposition"].endswith('report-example-report.csv"')
        assert client.get("/api/v1/public-api/projects/9999/report", headers=api_headers).status_code == 404
    finally:
        app.dependency_overrides.clear()
