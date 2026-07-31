import hashlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.db import Base, get_db
from api.main import app
from api.models import Membership, TeamInvitation, Tenant, User


@pytest.fixture()
def team_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    engine = create_engine(f"sqlite:///{tmp_path / 'team.sqlite'}")
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
        yield test_client, session_factory
    app.dependency_overrides.clear()


def _register(client, email, tenant_name=None, invitation_token=None):
    body = {"email": email, "password": "correct-horse-battery"}
    if tenant_name:
        body["tenant_name"] = tenant_name
    if invitation_token:
        body["invitation_token"] = invitation_token
    return client.post("/api/v1/auth/register", json=body)


def _login(client, email, tenant_id=None):
    body = {"email": email, "password": "correct-horse-battery"}
    if tenant_id:
        body["tenant_id"] = tenant_id
    response = client.post("/api/v1/auth/login", json=body)
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _invite(client, headers, email, role):
    response = client.post(
        "/api/v1/team/invitations",
        headers=headers,
        json={"email": email, "role": role},
    )
    assert response.status_code == 201
    return response.json()


def test_new_user_invitation_registers_directly_into_team_and_never_stores_plain_token(team_client):
    client, session_factory = team_client
    owner = _register(client, "owner@example.com", "tenant-a")
    assert owner.status_code == 201
    tenant_id = owner.json()["tenant"]["id"]
    owner_headers = _login(client, "owner@example.com")

    created = _invite(client, owner_headers, "editor@example.com", "editor")
    token = created["token"]
    assert token in created["invite_url"]
    assert created["invitation"]["status"] == "pending"
    with session_factory() as db:
        invitation = db.query(TeamInvitation).one()
        assert invitation.token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert token not in invitation.token_hash

    preview = client.get(f"/api/v1/team/invitations/preview/{token}")
    assert preview.status_code == 200
    assert preview.json()["tenant"] == {"id": tenant_id, "name": "tenant-a"}
    assert preview.json()["email"] == "editor@example.com"

    registered = _register(client, "editor@example.com", invitation_token=token)
    assert registered.status_code == 201
    assert registered.json()["tenant"]["id"] == tenant_id
    assert registered.json()["role"] == "editor"
    with session_factory() as db:
        assert db.query(Tenant).count() == 1
        editor = db.query(User).filter(User.email == "editor@example.com").one()
        membership = db.get(Membership, {"tenant_id": tenant_id, "user_id": editor.id})
        assert membership.role == "editor"
        assert db.query(TeamInvitation).one().accepted_at is not None

    editor_headers = _login(client, "editor@example.com", tenant_id)
    assert client.get("/api/v1/team/members", headers=editor_headers).json()["current_role"] == "editor"
    assert client.post(
        "/api/v1/team/invitations",
        headers=editor_headers,
        json={"email": "blocked@example.com", "role": "viewer"},
    ).status_code == 403
    assert client.post(
        "/api/v1/projects/999/schedule",
        headers=editor_headers,
        json={"interval_days": 7},
    ).status_code == 404


def test_existing_user_accepts_invitation_switches_tenants_and_role_changes_apply_immediately(team_client):
    client, session_factory = team_client
    owner = _register(client, "owner@example.com", "tenant-a").json()
    tenant_id = owner["tenant"]["id"]
    owner_id = owner["user"]["id"]
    owner_headers = _login(client, "owner@example.com")

    existing = _register(client, "member@example.com", "personal").json()
    personal_tenant_id = existing["tenant"]["id"]
    personal_headers = _login(client, "member@example.com")
    invitation = _invite(client, owner_headers, "member@example.com", "viewer")

    accepted = client.post(
        "/api/v1/team/invitations/accept",
        headers=personal_headers,
        json={"token": invitation["token"]},
    )
    assert accepted.status_code == 200
    team_headers = {"Authorization": f"Bearer {accepted.json()['access_token']}"}
    current = client.get("/api/v1/me", headers=team_headers)
    assert current.json()["tenant"]["id"] == tenant_id
    assert current.json()["role"] == "viewer"
    assert {item["id"] for item in current.json()["workspaces"]} == {tenant_id, personal_tenant_id}

    assert client.get("/api/v1/projects", headers=team_headers).status_code == 200
    assert client.post(
        "/api/v1/projects",
        headers=team_headers,
        json={"url": "https://blocked.example"},
    ).status_code == 403
    assert client.post(
        "/api/v1/projects/999/schedule",
        headers=team_headers,
        json={"interval_days": 7},
    ).status_code == 403
    assert client.put(
        "/api/v1/projects/999/content",
        headers=team_headers,
        json={"path": "q001.md", "text": "blocked"},
    ).status_code == 403
    assert client.post(
        "/api/v1/projects/999/tickets",
        headers=team_headers,
        json={
            "url": "https://outside.example/page",
            "ask_text": "Update the page",
            "influenced_questions": ["q001"],
        },
    ).status_code == 403
    assert client.post(
        "/api/v1/projects/999/publishing/github",
        headers=team_headers,
        json={"path": "content/q001.md", "confirmed": True},
    ).status_code == 403
    member_id = current.json()["user"]["id"]
    promoted = client.patch(
        f"/api/v1/team/members/{member_id}",
        headers=owner_headers,
        json={"role": "editor"},
    )
    assert promoted.status_code == 200
    assert client.post(
        "/api/v1/projects/999/schedule",
        headers=team_headers,
        json={"interval_days": 7},
    ).status_code == 404
    assert client.put(
        "/api/v1/settings/keys",
        headers=team_headers,
        json={"engine_code": "openai", "key_value": "blocked"},
    ).status_code == 403
    assert client.post(
        "/api/v1/billing/subscribe",
        headers=team_headers,
        json={"plan": "pro"},
    ).status_code == 403
    assert client.put(
        "/api/v1/projects/999/publishing/github",
        headers=team_headers,
        json={"credentials": {"GITHUB_TOKEN": "blocked"}},
    ).status_code == 403
    assert client.put(
        "/api/v1/projects/999/content",
        headers=team_headers,
        json={"path": "q001.md", "text": "allowed role"},
    ).status_code == 404
    assert client.post(
        "/api/v1/projects/999/publishing/github",
        headers=team_headers,
        json={"path": "content/q001.md", "confirmed": True},
    ).status_code == 404

    switched = client.post(
        "/api/v1/auth/switch-tenant",
        headers=team_headers,
        json={"tenant_id": personal_tenant_id},
    )
    assert switched.status_code == 200
    personal_again = {"Authorization": f"Bearer {switched.json()['access_token']}"}
    assert client.get("/api/v1/me", headers=personal_again).json()["tenant"]["id"] == personal_tenant_id

    assert client.patch(
        f"/api/v1/team/members/{owner_id}",
        headers=owner_headers,
        json={"role": "viewer"},
    ).status_code == 409
    assert client.delete(f"/api/v1/team/members/{owner_id}", headers=owner_headers).status_code == 409
    assert client.delete(f"/api/v1/team/members/{member_id}", headers=owner_headers).status_code == 200
    assert client.post(
        "/api/v1/team/invitations/accept",
        headers=personal_headers,
        json={"token": invitation["token"]},
    ).status_code == 404


def test_invitation_mismatch_rotation_revoke_and_owner_only_listing(team_client):
    client, session_factory = team_client
    _register(client, "owner@example.com", "tenant-a")
    owner_headers = _login(client, "owner@example.com")
    _register(client, "wrong@example.com", "wrong-team")
    wrong_headers = _login(client, "wrong@example.com")

    first = _invite(client, owner_headers, "invitee@example.com", "viewer")
    second = _invite(client, owner_headers, "invitee@example.com", "editor")
    assert first["invitation"]["id"] == second["invitation"]["id"]
    assert first["token"] != second["token"]
    assert client.get(f"/api/v1/team/invitations/preview/{first['token']}").status_code == 404
    assert client.post(
        "/api/v1/team/invitations/accept",
        headers=wrong_headers,
        json={"token": second["token"]},
    ).status_code == 403
    assert client.get("/api/v1/team/invitations", headers=wrong_headers).json() == {"invitations": []}

    listed = client.get("/api/v1/team/invitations", headers=owner_headers)
    assert listed.status_code == 200
    assert listed.json()["invitations"][0]["role"] == "editor"
    assert second["token"] not in listed.text
    invitation_id = second["invitation"]["id"]
    assert client.delete(f"/api/v1/team/invitations/{invitation_id}", headers=owner_headers).status_code == 200
    with session_factory() as db:
        assert db.query(TeamInvitation).count() == 0
