import base64
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.adapters import engine as engine_adapter
from api.adapters import outreach
from api.db import Base, get_db
from api.main import app
from api.models import IntegrationCredential, Job, Project
from api.settings.crypto import decrypt_key


@pytest.fixture()
def outreach_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    monkeypatch.setenv("AES_KEY", base64.urlsafe_b64encode(b"0" * 32).decode())
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    engine = create_engine(f"sqlite:///{tmp_path / 'outreach.sqlite'}")
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


def _register(client, email="owner@example.com", tenant_name="tenant-a"):
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery", "tenant_name": tenant_name},
    ).json()
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery"},
    ).json()
    return registered, {"Authorization": f"Bearer {login['access_token']}"}


def _seed_project(session_factory, tmp_path, tenant_id, tenant_name="tenant-a"):
    with session_factory() as db:
        project = Project(
            tenant_id=tenant_id,
            slug="example-com",
            url="https://example.com",
            market="global",
            status="ready",
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        project_id = project.id
    root = tmp_path / "work" / tenant_name / "example-com"
    root.mkdir(parents=True)
    (root / "geo.json").write_text(json.dumps({
        "slug": "example-com",
        "market": "global",
        "brand": {"name": "Example", "site": "https://example.com"},
    }), "utf-8")
    (root / "tasks.json").write_text(json.dumps({
        "summary": {"total": 1},
        "tasks": [{
            "id": "M-001",
            "kind": "offsite",
            "source": "manual",
            "url": "https://directory.example/vendors/example",
            "ask_text": "Add the official website and current pricing source.",
            "action": "Ask the editor to update the listing.",
            "status": "todo",
        }],
    }), "utf-8")
    return project_id, root


def _configure_smtp(client, project_id, headers):
    return client.put(
        f"/api/v1/projects/{project_id}/outreach/smtp",
        headers=headers,
        json={
            "host": "smtp.example.com",
            "port": 587,
            "security_mode": "starttls",
            "username": "mailer@example.com",
            "password": "smtp-password-secret",
            "from_email": "hello@example.com",
            "from_name": "Example team",
        },
    )


def test_smtp_credentials_are_encrypted_hidden_and_tenant_isolated(outreach_client):
    client, session_factory, tmp_path = outreach_client
    registered, headers = _register(client)
    tenant_id = registered["tenant"]["id"]
    project_id, _root = _seed_project(session_factory, tmp_path, tenant_id)

    configured = _configure_smtp(client, project_id, headers)
    assert configured.status_code == 200
    assert configured.json()["smtp"] == {
        "configured": True,
        "host": "smtp.example.com",
        "port": 587,
        "security_mode": "starttls",
        "username": "mailer@example.com",
        "from_email": "hello@example.com",
        "from_name": "Example team",
        "password_configured": True,
    }
    assert "smtp-password-secret" not in configured.text
    with session_factory() as db:
        row = db.query(IntegrationCredential).one()
        assert row.provider == "outreach_smtp"
        assert "smtp-password-secret" not in row.encrypted_value
        assert json.loads(decrypt_key(row.encrypted_value))["password"] == "smtp-password-secret"

    _other, other_headers = _register(client, "other@example.net", "tenant-b")
    assert client.get(f"/api/v1/projects/{project_id}/outreach", headers=other_headers).status_code == 404
    assert client.put(
        f"/api/v1/projects/{project_id}/outreach/smtp",
        headers=other_headers,
        json={
            "host": "smtp.other.test",
            "port": 465,
            "security_mode": "ssl",
            "from_email": "hello@other.test",
        },
    ).status_code == 404


def test_smtp_send_blocks_private_destination(monkeypatch):
    monkeypatch.setattr(outreach.smtplib, "SMTP", lambda *args, **kwargs: pytest.fail("SMTP connection attempted"))
    draft = {
        "id": "outreach-test",
        "recipient_email": "recipient@example.com",
        "subject": "Subject",
        "body": "Body",
    }
    settings = {
        "host": "127.0.0.1",
        "port": 587,
        "security_mode": "starttls",
        "from_email": "sender@example.com",
        "from_name": "Sender",
    }
    with pytest.raises(outreach.OutreachError, match="outreach_smtp_host_blocked"):
        outreach.send_smtp(draft, settings, {})


def test_outreach_requires_current_revision_and_explicit_human_confirmation(
    outreach_client,
    monkeypatch,
):
    client, session_factory, tmp_path = outreach_client
    registered, headers = _register(client)
    tenant_id = registered["tenant"]["id"]
    project_id, root = _seed_project(session_factory, tmp_path, tenant_id)
    assert _configure_smtp(client, project_id, headers).status_code == 200

    created = client.post(
        f"/api/v1/projects/{project_id}/outreach/drafts",
        headers=headers,
        json={"ticket_id": "M-001", "recipient_email": "Editor@Directory.example"},
    )
    assert created.status_code == 201
    draft = created.json()["draft"]
    assert draft["status"] == "draft"
    assert draft["revision"] == 1
    assert draft["recipient_email"] == "editor@directory.example"
    assert "Add the official website" in draft["body"]

    unconfirmed = client.post(
        f"/api/v1/projects/{project_id}/outreach/drafts/{draft['id']}/send",
        headers=headers,
        json={"revision": 1, "confirmed": False, "confirmation_text": ""},
    )
    assert unconfirmed.status_code == 400
    assert unconfirmed.json()["error"] == "outreach_confirmation_required"

    updated = client.put(
        f"/api/v1/projects/{project_id}/outreach/drafts/{draft['id']}",
        headers=headers,
        json={
            "revision": 1,
            "recipient_email": draft["recipient_email"],
            "subject": "Please update the Example listing",
            "body": draft["body"] + "\n\nReference: https://example.com/pricing",
        },
    )
    assert updated.status_code == 200
    draft = updated.json()["draft"]
    assert draft["revision"] == 2

    stale = client.post(
        f"/api/v1/projects/{project_id}/outreach/drafts/{draft['id']}/send",
        headers=headers,
        json={"revision": 1, "confirmed": True, "confirmation_text": f"SEND {draft['id']}"},
    )
    assert stale.status_code == 409
    assert stale.json()["error"] == "outreach_revision_conflict"
    wrong_text = client.post(
        f"/api/v1/projects/{project_id}/outreach/drafts/{draft['id']}/send",
        headers=headers,
        json={"revision": 2, "confirmed": True, "confirmation_text": "SEND"},
    )
    assert wrong_text.status_code == 400
    assert wrong_text.json()["error"] == "outreach_confirmation_required"

    queued_calls = []
    from api.outreach import router as outreach_router

    monkeypatch.setattr(
        outreach_router.task_send_outreach,
        "delay",
        lambda *args, **kwargs: queued_calls.append((args, kwargs)),
    )
    queued = client.post(
        f"/api/v1/projects/{project_id}/outreach/drafts/{draft['id']}/send",
        headers=headers,
        json={
            "revision": 2,
            "confirmed": True,
            "confirmation_text": f"SEND {draft['id']}",
        },
    )
    assert queued.status_code == 202
    assert queued_calls[0][0] == ("tenant-a", "example-com", draft["id"])
    state = json.loads((root / "outreach" / "state.json").read_text("utf-8"))
    stored = state["drafts"][0]
    assert stored["status"] == "queued"
    assert stored["confirmed_revision"] == 2
    assert stored["confirmed_by_user_id"] == registered["user"]["id"]
    assert len(stored["confirmed_content_hash"]) == 64


def test_outreach_worker_claims_confirmed_snapshot_and_records_send(outreach_client, monkeypatch):
    client, session_factory, tmp_path = outreach_client
    registered, headers = _register(client)
    tenant_id = registered["tenant"]["id"]
    project_id, root = _seed_project(session_factory, tmp_path, tenant_id)
    assert _configure_smtp(client, project_id, headers).status_code == 200
    draft = client.post(
        f"/api/v1/projects/{project_id}/outreach/drafts",
        headers=headers,
        json={"ticket_id": "M-001", "recipient_email": "editor@directory.example"},
    ).json()["draft"]

    from api.outreach import router as outreach_router

    monkeypatch.setattr(outreach_router.task_send_outreach, "delay", lambda *args, **kwargs: None)
    queued = client.post(
        f"/api/v1/projects/{project_id}/outreach/drafts/{draft['id']}/send",
        headers=headers,
        json={
            "revision": draft["revision"],
            "confirmed": True,
            "confirmation_text": f"SEND {draft['id']}",
        },
    ).json()
    job_id = queued["job_id"]

    from api.worker import tasks

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    sent = []

    def fake_send(current, settings, credentials):
        sent.append({"draft": dict(current), "settings": settings, "credentials": credentials})
        return {"message_id": "<message@example.com>", "recipient_email": current["recipient_email"]}

    monkeypatch.setattr(outreach, "send_smtp", fake_send)
    result = tasks.task_send_outreach.run("tenant-a", "example-com", draft["id"], job_id=job_id)
    assert result["message_id"] == "<message@example.com>"
    assert len(sent) == 1
    assert sent[0]["draft"]["status"] == "sending"
    assert sent[0]["settings"]["host"] == "smtp.example.com"
    assert sent[0]["credentials"] == {
        "username": "mailer@example.com",
        "password": "smtp-password-secret",
    }
    with session_factory() as db:
        assert db.get(Job, job_id).status == "done"
    state = json.loads((root / "outreach" / "state.json").read_text("utf-8"))
    assert state["drafts"][0]["status"] == "sent"
    assert state["drafts"][0]["sent_at"]
    with engine_adapter.with_tenant_context("tenant-a", "example-com"):
        with pytest.raises(outreach.OutreachError, match="outreach_draft_not_queued"):
            outreach.claim_for_sending("example-com", draft["id"])


def test_outreach_worker_releases_queued_draft_if_smtp_was_removed(outreach_client, monkeypatch):
    client, session_factory, tmp_path = outreach_client
    registered, headers = _register(client)
    tenant_id = registered["tenant"]["id"]
    project_id, root = _seed_project(session_factory, tmp_path, tenant_id)
    assert _configure_smtp(client, project_id, headers).status_code == 200
    draft = client.post(
        f"/api/v1/projects/{project_id}/outreach/drafts",
        headers=headers,
        json={"ticket_id": "M-001", "recipient_email": "editor@directory.example"},
    ).json()["draft"]
    from api.outreach import router as outreach_router

    monkeypatch.setattr(outreach_router.task_send_outreach, "delay", lambda *args, **kwargs: None)
    queued = client.post(
        f"/api/v1/projects/{project_id}/outreach/drafts/{draft['id']}/send",
        headers=headers,
        json={
            "revision": draft["revision"],
            "confirmed": True,
            "confirmation_text": f"SEND {draft['id']}",
        },
    ).json()
    assert client.delete(f"/api/v1/projects/{project_id}/outreach/smtp", headers=headers).status_code == 200

    from api.worker import tasks

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    with pytest.raises(outreach.OutreachError, match="smtp_not_configured"):
        tasks.task_send_outreach.run(
            "tenant-a",
            "example-com",
            draft["id"],
            job_id=queued["job_id"],
        )
    state = json.loads((root / "outreach" / "state.json").read_text("utf-8"))
    assert state["drafts"][0]["status"] == "failed"
    with session_factory() as db:
        assert db.get(Job, queued["job_id"]).status == "failed"
