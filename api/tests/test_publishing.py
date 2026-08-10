import base64
import json
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.adapters import engine as engine_adapter
from api.adapters import publishing
from api.adapters.engine import load_tenant_keys
from api.db import Base, get_db
from api.main import app
from api.models import ApiKey, Project


@pytest.fixture()
def publishing_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    monkeypatch.setenv("AES_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    engine = create_engine(f"sqlite:///{tmp_path / 'publishing.sqlite'}")
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


def _register(client, email, tenant_name):
    result = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery", "tenant_name": tenant_name},
    ).json()
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery"},
    ).json()
    return result["tenant"]["id"], {"Authorization": f"Bearer {login['access_token']}"}


def _seed_project(session_factory, tmp_path, tenant_id, tenant_name="tenant-a"):
    with session_factory() as db:
        project = Project(
            tenant_id=tenant_id,
            slug="example-com",
            url="https://example.com",
            market="both",
            status="ready",
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        project_id = project.id
    root = tmp_path / "work" / tenant_name / "example-com"
    (root / "content").mkdir(parents=True)
    (root / "geo.json").write_text(json.dumps({
        "slug": "example-com",
        "market": "both",
        "brand": {"name": "Example", "site": "https://example.com"},
    }), "utf-8")
    (root / "content" / "q001-final.md").write_text("# Verified guide\n\nFinal content.", "utf-8")
    return project_id, root


def _configure_github(client, project_id, headers):
    return client.put(
        f"/api/v1/projects/{project_id}/publishing/github",
        headers=headers,
        json={
            "credentials": {"GITHUB_TOKEN": "github-secret-token"},
            "config": {"repo": "owner/site", "branch": "main", "dir": "docs/geo"},
        },
    )


def test_publisher_config_is_encrypted_tenant_isolated_and_hidden_from_engine_keys(publishing_client):
    client, session_factory, tmp_path = publishing_client
    tenant_id, headers = _register(client, "owner@example.com", "tenant-a")
    project_id, root = _seed_project(session_factory, tmp_path, tenant_id)

    initial = client.get(f"/api/v1/projects/{project_id}/publishing", headers=headers)
    assert initial.status_code == 200
    assert [item["code"] for item in initial.json()["publishers"]] == [
        "github", "wordpress", "wechat_draft", "webhook",
    ]
    github = initial.json()["publishers"][0]
    assert github["missing"] == ["GITHUB_TOKEN", "repo"]
    assert not github["ready"]

    configured = _configure_github(client, project_id, headers)
    assert configured.status_code == 200
    github = next(item for item in configured.json()["publishers"] if item["code"] == "github")
    assert github["ready"]
    assert github["missing"] == []
    assert {item["key"]: item["value"] for item in github["cfg"]} == {
        "repo": "owner/site",
        "branch": "main",
        "dir": "docs/geo",
    }
    assert "github-secret-token" not in configured.text
    assert client.get("/api/v1/settings/keys", headers=headers).json() == {"keys": []}

    with session_factory() as db:
        stored = db.query(ApiKey).one()
        assert stored.engine_code == publishing.credential_code("github", "GITHUB_TOKEN")
        assert stored.encrypted_value != "github-secret-token"
        assert load_tenant_keys(db, tenant_id) == {}
    config = json.loads((root / "geo.json").read_text("utf-8"))
    assert config["publishing"]["github"]["repo"] == "owner/site"
    assert "github-secret-token" not in (root / "geo.json").read_text("utf-8")

    _, other_headers = _register(client, "other@example.com", "tenant-b")
    assert client.get(f"/api/v1/projects/{project_id}/publishing", headers=other_headers).status_code == 404
    assert client.put(
        f"/api/v1/projects/{project_id}/publishing/github",
        headers=other_headers,
        json={"credentials": {"GITHUB_TOKEN": "other-token"}},
    ).status_code == 404


def test_publish_requires_confirmation_injects_only_tenant_credentials_and_records_result(
    publishing_client, monkeypatch,
):
    client, session_factory, tmp_path = publishing_client
    tenant_id, headers = _register(client, "owner@example.com", "tenant-a")
    project_id, root = _seed_project(session_factory, tmp_path, tenant_id)
    assert _configure_github(client, project_id, headers).status_code == 200
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    unconfirmed = client.post(
        f"/api/v1/projects/{project_id}/publishing/github",
        headers=headers,
        json={"path": "content/q001-final.md"},
    )
    assert unconfirmed.status_code == 400
    assert unconfirmed.json()["error"] == "publish_confirmation_required"

    import publish as engine_publish

    captured = {}

    def fake_github(config, text, title, filename):
        captured.update({
            "config": config,
            "text": text,
            "title": title,
            "filename": filename,
            "token": os.environ.get("GITHUB_TOKEN"),
        })
        return {"ok": True, "url": "https://github.com/owner/site/blob/main/docs/geo/q001-final.md"}

    monkeypatch.setitem(engine_publish._IMPL, "github", fake_github)
    published = client.post(
        f"/api/v1/projects/{project_id}/publishing/github",
        headers=headers,
        json={"path": "content/q001-final.md", "confirmed": True},
    )
    assert published.status_code == 200
    assert published.json()["ok"]
    assert captured == {
        "config": {"repo": "owner/site", "branch": "main", "dir": "docs/geo"},
        "text": "# Verified guide\n\nFinal content.",
        "title": "Verified guide",
        "filename": "q001-final.md",
        "token": "github-secret-token",
    }
    assert "GITHUB_TOKEN" not in os.environ
    records = json.loads((root / "publish.json").read_text("utf-8"))
    assert records[0]["platform"] == "github"
    assert records[0]["path"] == "content/q001-final.md"

    traversal = client.post(
        f"/api/v1/projects/{project_id}/publishing/github",
        headers=headers,
        json={"path": "content/../../geo.json", "confirmed": True},
    )
    assert traversal.status_code == 200
    assert traversal.json() == {"ok": False, "error": "文件不可用：content/../../geo.json"}

    def unavailable(*args, **kwargs):
        import requests

        raise requests.ConnectionError("token must not appear in the API response")

    monkeypatch.setitem(engine_publish._IMPL, "github", unavailable)
    failed = client.post(
        f"/api/v1/projects/{project_id}/publishing/github",
        headers=headers,
        json={"path": "content/q001-final.md", "confirmed": True},
    )
    assert failed.status_code == 200
    assert failed.json() == {
        "ok": False,
        "error": "发布渠道请求失败，请检查渠道地址、凭证和网络连接",
    }
    assert "token must not appear" not in failed.text
    assert "GITHUB_TOKEN" not in os.environ


def test_wordpress_and_wechat_engine_contracts_create_drafts_only(monkeypatch):
    import publish as engine_publish

    class FakeResponse:
        status_code = 201

        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    wordpress_request = {}

    def wordpress_post(url, **kwargs):
        wordpress_request.update({"url": url, **kwargs})
        return FakeResponse({"link": "https://blog.example.com/?p=7"})

    monkeypatch.setenv("WP_USER", "editor")
    monkeypatch.setenv("WP_APP_PASSWORD", "application-password")
    monkeypatch.setattr(engine_publish.requests, "post", wordpress_post)
    result = engine_publish._pub_wordpress(
        {"site_url": "https://blog.example.com"}, "# Final", "Final", "final.md",
    )
    assert result["ok"]
    assert wordpress_request["json"]["status"] == "draft"

    wechat_requests = []
    monkeypatch.setenv("WECHAT_APPID", "appid")
    monkeypatch.setenv("WECHAT_APPSECRET", "secret")
    monkeypatch.setattr(
        engine_publish.requests,
        "get",
        lambda *args, **kwargs: FakeResponse({"access_token": "access-token"}),
    )

    def wechat_post(url, **kwargs):
        wechat_requests.append({"url": url, **kwargs})
        return FakeResponse({"media_id": "draft-media"})

    monkeypatch.setattr(engine_publish.requests, "post", wechat_post)
    result = engine_publish._pub_wechat(
        {"thumb_media_id": "cover-media"}, "# Final", "Final", "final.md",
    )
    assert result["ok"]
    assert "/cgi-bin/draft/add" in wechat_requests[0]["url"]
    assert "freepublish" not in wechat_requests[0]["url"]


def test_publishing_destinations_reject_insecure_and_private_urls():
    with pytest.raises(ValueError, match="public HTTPS host"):
        publishing.validate_config("wordpress", {"site_url": "http://blog.example.com"})
    with pytest.raises(ValueError, match="public HTTPS host"):
        publishing.validate_config("wordpress", {"site_url": "https://127.0.0.1"})
    with pytest.raises(ValueError, match="public HTTPS host"):
        publishing.validate_credentials("webhook", {"PUBLISH_WEBHOOK_URL": "https://169.254.169.254/hook"})
