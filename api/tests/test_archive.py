import io
import json
import tarfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.adapters import archive
from api.adapters import engine as engine_adapter
from api.db import Base, get_db
from api.main import app
from api.models import Job, Project


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.deleted = []

    def upload_fileobj(self, handle, bucket, key, ExtraArgs=None):
        body = handle.read()
        self.objects[(bucket, key)] = {
            "body": body,
            "metadata": dict((ExtraArgs or {}).get("Metadata") or {}),
        }

    def head_object(self, Bucket, Key):
        value = self.objects[(Bucket, Key)]
        return {"ContentLength": len(value["body"]), "Metadata": value["metadata"]}

    def download_fileobj(self, bucket, key, output):
        output.write(self.objects[(bucket, key)]["body"])

    def delete_object(self, Bucket, Key):
        self.deleted.append((Bucket, Key))
        self.objects.pop((Bucket, Key), None)


@pytest.fixture()
def archive_client(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-that-is-long-enough-32")
    monkeypatch.setenv("OBJECT_STORAGE_BUCKET", "archive-bucket")
    monkeypatch.setenv("OBJECT_STORAGE_ENDPOINT_URL", "https://objects.example.test")
    monkeypatch.setenv("OBJECT_STORAGE_ACCESS_KEY_ID", "access-secret")
    monkeypatch.setenv("OBJECT_STORAGE_SECRET_ACCESS_KEY", "storage-secret")
    monkeypatch.setenv("OBJECT_STORAGE_PREFIX", "cold")
    monkeypatch.setenv("OBJECT_STORAGE_RETENTION_COUNT", "2")
    monkeypatch.setattr(engine_adapter, "WORK_ROOT", tmp_path / "work")
    engine = create_engine(f"sqlite:///{tmp_path / 'archive.sqlite'}")
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


def _seed_project(session_factory, tmp_path, tenant_id, slug="example-com"):
    with session_factory() as db:
        project = Project(
            tenant_id=tenant_id,
            slug=slug,
            url="https://example.com",
            market="global",
            status="ready",
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        project_id = project.id
    root = tmp_path / "work" / "tenant-a" / slug
    (root / "metrics").mkdir(parents=True)
    (root / "metrics" / "2026-07-31.json").write_text('{"visibility":42}\n', "utf-8")
    (root / "audit.json").write_text('{"score":80}\n', "utf-8")
    (root / ".jobs").mkdir()
    (root / ".jobs" / "99.log").write_text("not a pipeline artifact\n", "utf-8")
    return project_id, root


def test_archive_api_is_tenant_isolated_and_requires_restore_confirmation(archive_client, monkeypatch):
    client, session_factory, tmp_path = archive_client
    registered, headers = _register(client)
    project_id, _root = _seed_project(session_factory, tmp_path, registered["tenant"]["id"])

    overview = client.get(f"/api/v1/projects/{project_id}/archives", headers=headers)
    assert overview.status_code == 200
    assert overview.json()["storage"] == {
        "configured": True,
        "bucket": "archive-bucket",
        "endpoint_type": "s3_compatible",
        "region": "us-east-1",
        "prefix": "cold",
        "retention_count": 2,
        "server_side_encryption": None,
        "filesystem_ssot": True,
    }
    assert "access-secret" not in overview.text
    assert "storage-secret" not in overview.text

    from api.archive import router as archive_router

    queued = []
    monkeypatch.setattr(
        archive_router.task_archive_project,
        "delay",
        lambda *args, **kwargs: queued.append((args, kwargs)),
    )
    created = client.post(f"/api/v1/projects/{project_id}/archives", headers=headers)
    assert created.status_code == 202
    assert queued[0][0] == ("tenant-a", "example-com")
    with session_factory() as db:
        job = db.get(Job, created.json()["job_id"])
        job.status = "done"
        db.commit()

    fake = FakeS3()
    monkeypatch.setattr(archive, "_client", lambda settings=None: fake)
    entry = archive.create_archive("tenant-a", "example-com")
    wrong = client.post(
        f"/api/v1/projects/{project_id}/archives/{entry['id']}/restore",
        headers=headers,
        json={"confirmed": True, "confirmation_text": "RESTORE", "overwrite": False},
    )
    assert wrong.status_code == 400
    assert wrong.json()["error"] == "archive_restore_confirmation_required"

    restore_calls = []
    monkeypatch.setattr(
        archive_router.task_restore_project,
        "delay",
        lambda *args, **kwargs: restore_calls.append((args, kwargs)),
    )
    restored = client.post(
        f"/api/v1/projects/{project_id}/archives/{entry['id']}/restore",
        headers=headers,
        json={
            "confirmed": True,
            "confirmation_text": f"RESTORE {entry['id']}",
            "overwrite": True,
        },
    )
    assert restored.status_code == 202
    assert restore_calls[0][0] == ("tenant-a", "example-com", entry["id"], True)

    _other, other_headers = _register(client, "other@example.net", "tenant-b")
    assert client.get(f"/api/v1/projects/{project_id}/archives", headers=other_headers).status_code == 404
    assert client.post(f"/api/v1/projects/{project_id}/archives", headers=other_headers).status_code == 404


def test_archive_worker_verifies_snapshot_and_restore_conflicts(archive_client, monkeypatch):
    client, session_factory, tmp_path = archive_client
    registered, _headers = _register(client)
    project_id, root = _seed_project(session_factory, tmp_path, registered["tenant"]["id"])
    fake = FakeS3()
    monkeypatch.setattr(archive, "_client", lambda settings=None: fake)

    with session_factory() as db:
        job = Job(project_id=project_id, action="archive", status="queued")
        db.add(job)
        db.commit()
        db.refresh(job)
        archive_job_id = job.id

    from api.worker import tasks

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    result = tasks.task_archive_project.run("tenant-a", "example-com", job_id=archive_job_id)
    entry = result["archive"]
    assert entry["file_count"] == 2
    assert entry["object_key"].startswith("cold/tenant-a/example-com/")
    stored = fake.objects[("archive-bucket", entry["object_key"])]
    assert stored["metadata"]["sha256"] == entry["sha256"]
    with tarfile.open(fileobj=io.BytesIO(stored["body"]), mode="r:gz") as snapshot:
        assert set(snapshot.getnames()) == {
            archive.SNAPSHOT_MANIFEST_NAME,
            "audit.json",
            "metrics/2026-07-31.json",
        }
    assert json.loads((root / ".citeaura" / "archives.json").read_text("utf-8"))["archives"][0]["id"] == entry["id"]
    with session_factory() as db:
        assert db.get(Job, archive_job_id).status == "done"

    (root / "audit.json").write_text('{"score":10}\n', "utf-8")
    with session_factory() as db:
        job = Job(project_id=project_id, action="archive_restore", status="queued")
        db.add(job)
        db.commit()
        db.refresh(job)
        conflict_job_id = job.id
    with pytest.raises(archive.ArchiveError, match="archive_restore_conflict"):
        tasks.task_restore_project.run(
            "tenant-a",
            "example-com",
            entry["id"],
            overwrite=False,
            job_id=conflict_job_id,
        )
    with session_factory() as db:
        assert db.get(Job, conflict_job_id).status == "failed"

    with session_factory() as db:
        job = Job(project_id=project_id, action="archive_restore", status="queued")
        db.add(job)
        db.commit()
        db.refresh(job)
        restore_job_id = job.id
    restored = tasks.task_restore_project.run(
        "tenant-a",
        "example-com",
        entry["id"],
        overwrite=True,
        job_id=restore_job_id,
    )
    assert restored["restore"]["status"] == "restored"
    assert (root / "audit.json").read_text("utf-8") == '{"score":80}\n'
    with session_factory() as db:
        assert db.get(Job, restore_job_id).status == "done"


def test_archive_retention_expires_old_objects(archive_client, monkeypatch):
    client, session_factory, tmp_path = archive_client
    registered, _headers = _register(client)
    _project_id, root = _seed_project(session_factory, tmp_path, registered["tenant"]["id"])
    monkeypatch.setenv("OBJECT_STORAGE_RETENTION_COUNT", "1")
    fake = FakeS3()
    monkeypatch.setattr(archive, "_client", lambda settings=None: fake)

    first = archive.create_archive("tenant-a", "example-com")
    (root / "audit.json").write_text('{"score":81}\n', "utf-8")
    second = archive.create_archive("tenant-a", "example-com")
    entries = archive.list_archives("tenant-a", "example-com")
    by_id = {entry["id"]: entry for entry in entries}
    assert by_id[first["id"]]["status"] == "expired"
    assert by_id[second["id"]]["status"] == "available"
    assert ("archive-bucket", first["object_key"]) in fake.deleted
    assert ("archive-bucket", second["object_key"]) in fake.objects
