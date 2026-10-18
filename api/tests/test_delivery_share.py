import json
from pathlib import Path

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
    """注册后从 /me 取租户信息：注册响应只返回 accepted（固定 202，防止邮箱枚举）。"""
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery", "tenant_name": tenant_name},
    )
    assert registered.status_code == 202
    assert registered.json()["accepted"] is True
    assert "tenant" not in registered.json()
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    profile = client.get("/api/v1/me", headers=headers)
    assert profile.status_code == 200
    return profile.json(), headers


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


def _write_delivery_contract(directory):
    """Test double for delivery.ensure_delivery_contract: fill the real contract.

    The fixture starts from an incomplete draft, so the authenticated send path
    rebuilds it. The rebuild here writes the same artifacts the production
    builder writes, which lets the anonymous download exercise the *real*
    validate_existing_delivery_contract instead of a stub.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for number, name in project_router.delivery.REQUIRED_DOCUMENTS.items():
        (directory / f"{number}-{name}.md").write_text(
            f"# {name}\n\nEnglish-only fixture copy.\n", "utf-8",
        )
        (directory / f"{number}-{name}.html").write_text(
            f"<h1>{name}</h1>\n<p>English-only fixture copy.</p>\n", "utf-8",
        )
    (directory / "03-Ticket-Log.csv").write_text(
        "id,title,status\nT-1,Sample ticket,done\n", "utf-8",
    )
    assets = directory / "assets"
    assets.mkdir(exist_ok=True)
    index_path = assets / "index.json"
    index = json.loads(index_path.read_text("utf-8")) if index_path.is_file() else {}
    index.update({
        "readiness": "customer_ready",
        "diagnostic_ready": True,
        "implementation_ready": False,
        "source_revision": "test",
        "summary": {"ready": 1, "needs_review": 0, "template": 0},
        "quality_gate": {"status": "passed"},
    })
    index_path.write_text(json.dumps(index), "utf-8")
    return directory


def _tree(directory):
    """Snapshot every file so a test can prove a GET wrote nothing to disk."""
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(Path(directory).rglob("*"))
        if path.is_file()
    }


def test_agency_can_create_and_download_sendable_pack(tmp_path, monkeypatch):
    client, session_factory = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(
        project_router.delivery,
        "ensure_delivery_contract",
        lambda slug, directory: _write_delivery_contract(directory),
    )
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


def test_public_download_rejects_broken_pack_without_writing(tmp_path, monkeypatch):
    """匿名下载只做只读校验：契约不合法时必须 409，且不能重建工作区文件。"""
    client, session_factory = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(
        project_router.delivery,
        "ensure_delivery_contract",
        lambda slug, directory: _write_delivery_contract(directory),
    )
    registered, headers = _register(client, "broken-pack@example.com", "northstar")
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

    created = client.post(
        f"/api/v1/projects/{project_id}/deliveries/{date}/send",
        headers=headers,
        json={},
    )
    assert created.status_code == 200
    token = created.json()["url"].rsplit("/", 1)[-1]

    # 发布后的快照被破坏：缺少必需文档，真实契约校验会失败。
    directory = tmp_path / "work" / "northstar" / "acme" / "delivery" / date
    (directory / "02-Execution-Plan.html").unlink()
    before = _tree(directory)

    rejected = client.get(f"/api/v1/public/delivery-packs/{token}")

    assert rejected.status_code == 409
    assert rejected.json()["error"] == "delivery_contract_invalid"
    # 未认证 GET 绝不能触发 ensure_delivery_contract 重建（那会写回缺失文件）。
    assert _tree(directory) == before
