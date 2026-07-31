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
    assert "/api/v1/auth/refresh" in response.text
    assert "async function refreshAccessToken()" in response.text
    assert "const rawFetch = window.fetch.bind(window)" in response.text
    assert "/api/v1/projects" in response.text
    assert "/api/v1/settings/keys" in response.text
    assert "disvorai_access_token" in response.text
    assert "job.status === 'queued' ? 'running'" in response.text
    assert "skip_llm:configuredKeyCount === 0" in response.text
    assert "document.querySelector('#ob-nosample')?.checked" in response.text
    assert "name:body.name || null" in response.text
    assert "data.job.log_offset || requested" in response.text
    assert "/api/v1/projects/actions" in response.text
    assert "'/actions/' + encodeURIComponent(action)" in response.text
    assert "if (action === 'serve') action = 'sample'" not in response.text
    assert "'/config'" in response.text
    assert "'/assets'" in response.text
    assert "'/workbench?qid='" in response.text
    assert "'/questions'" in response.text
    assert "创建 Offsite 工单" in response.text
    assert "offsiteTicketModal" in response.text
    assert "'/tickets'" in response.text
    assert "influenced_questions" in response.text
    assert "{ok:r.ok,task:data.ticket,error:data.error || data.detail}" in response.text
    assert "AES-256-GCM 加密保存" in response.text
    assert "Key 已加密保存" in response.text
    assert "<summary style=\"font-size:12.5px;color:var(--t500);cursor:pointer\">高级设置</summary>" in response.text
    assert '<span class="tag tag-dim">未测</span>' in response.text
    assert "写入项目根目录 .env" not in response.text
    assert "已写入 .env" not in response.text
    assert "单机自托管版，无账号体系" not in response.text
    assert 'onclick="setMonitor(' in response.text
    assert 'onclick="stopJob()"' not in response.text
    assert 'onclick="pubModal()"' in response.text
    assert "/api/v1/projects/' + id + '/publishing" in response.text
    assert "confirmed:true" in response.text
    assert "publisherEnvToCode" in response.text
    assert "publishing_not_available_in_mvp" not in response.text
    assert "凭证使用 AES-256-GCM 加密保存" in response.text
    assert "/api/v1/projects/' + id + '/samples/import" in response.text
    assert "人工·网页端" in response.text
    assert "x.sampling_mode" in response.text
    assert "/api/delivery-zip/" in response.text
    assert "'/deliveries/' + deliveryZipMatch[2]" in response.text
    assert "async function downloadDelivery(date)" in response.text
    assert "下载 ZIP" in response.text
    assert "URL.createObjectURL(await result.blob())" in response.text
    assert "采样为手动触发或由 schedule 驱动" in response.text
    assert "/api/v1/projects/' + id + '/schedule" in response.text
    assert "/api/v1/projects/' + id + '/framing" in response.text
    assert "Object.keys(updates).length === 1" in response.text
    assert "delete updates.monitor" in response.text
    assert "周期复跑" in response.text
    assert "async function setMonitor(days)" in response.text
    assert "由后台调度自动跑完整一期" in response.text
    assert "function framingPanel()" in response.text
    assert "function showFramingEvidence(index)" in response.text
    assert "const engineCompetitorsView = vCompetitors" in response.text
    assert "VIEWS.competitors = vCompetitors" in response.text
    assert "AI 如何描述你" in response.text
    assert "基于品牌被实际提及的回答短语，词频按样本去重。" in response.text
    assert "品牌印象加载失败，请刷新后重试。" in response.text
    assert "原文证据" in response.text
    assert "/api/v1/team/members" in response.text
    assert "/api/v1/team/invitations" in response.text
    assert "/api/v1/auth/switch-tenant" in response.text
    assert "invitation_token:invitationToken" in response.text
    assert "function teamPanel()" in response.text
    assert "function teamInviteModal()" in response.text
    assert "VIEWS.settings = vSettings" in response.text
    assert "团队成员按 owner/editor/viewer 分级" in response.text
    assert "成员邀请与角色管理暂未开放" not in response.text
    assert "/api/v1/settings/delivery-branding" in response.text
    assert "function deliveryBrandingPanel()" in response.text
    assert "function setDeliveryBrandingLogo(input)" in response.text
    assert "function saveDeliveryBranding()" in response.text
    assert "打印 / PDF 页眉" in response.text
    assert "Agency 套餐可用" in response.text
    assert "/api/v1/projects/' + id + '/sampling-funding" in response.text
    assert "function samplingFundingPanel(state)" in response.text
    assert "async function setPlatformPool(enabled)" in response.text
    assert "BYOK 始终优先" in response.text
    assert "API·联网" in response.text
    assert "API·参数化" in response.text
    assert "本月费用" in response.text
    assert "费用信息加载失败" in response.text
    assert "仅所有者可更改" in response.text
    assert "缺少 BYOK 的引擎将按页面所示单价逐次收费" in response.text
    assert 'class="settings-core-grid"' in response.text
    assert ".settings-core-grid{grid-template-columns:1fr!important}" in response.text
    assert "geo.py serve --slug" not in response.text
    assert "本产品不内置定时器" not in response.text
    assert "后台任务队列执行" in response.text
    assert "后台子进程执行" not in response.text
    assert "written to local .env" not in response.text
    assert "Credentials live in .env" not in response.text
    assert "background subprocesses" not in response.text
    assert "single-machine self-hosted, no account system" not in response.text
    assert "単機セルフホスト版" not in response.text
    assert "Download ZIP" in response.text


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
