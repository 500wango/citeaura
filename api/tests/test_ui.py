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
    response = TestClient(app).get("/app")

    assert response.status_code == 200
    assert "DisvorAI" in response.text
    assert "GeoLook" not in response.text
    assert 'Geo<span style="color:var(--accent)">Look</span>' not in response.text
    assert "/api/v1/auth/login" in response.text
    assert "/api/v1/auth/refresh" in response.text
    assert "/api/v1/auth/logout" in response.text
    assert "/api/v1/auth/password/forgot" in response.text
    assert "/api/v1/auth/password/reset" in response.text
    assert "async function refreshAccessToken()" in response.text
    assert "data-auth-mode=\"login\"" in response.text
    assert "data-auth-mode=\"register\"" in response.text
    assert "name=\"tenant_name\"" in response.text
    assert "name=\"confirm_password\"" in response.text
    assert "const resetToken = new URLSearchParams(location.search).get('reset_token')" in response.text
    assert "email_already_registered:'该邮箱已注册，请切换到登录。'" in response.text
    assert "if (!registered.result.ok)" in response.text
    assert "if (!r.ok) {\n        const registration" not in response.text
    assert "id = 'disvorai-logout'" in response.text
    assert "window.disvoraiLogout = logout" in response.text
    assert 'class="global-rail"' in response.text
    assert 'class="module-panel"' in response.text
    assert '#side{width:332px' in response.text
    assert '.global-rail{position:relative;z-index:2;width:108px' in response.text
    assert '.rail-action{position:relative;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;width:96px' in response.text
    assert '.module-panel{position:fixed;left:108px' in response.text
    assert 'class="project-switcher-row"' in response.text
    assert 'class="project-add"' in response.text
    assert '.project-add{display:flex;align-items:center;justify-content:center;gap:6px;width:100%;min-height:34px' in response.text
    assert "<span>${esc(adminText({zh:'添加品牌',en:'Add brand',ja:'ブランドを追加'}))}</span>" in response.text
    assert "onclick=\"startBrandOnboarding()\"" in response.text
    assert "function startBrandOnboarding()" in response.text
    assert "zh:'当前品牌',en:'Current brand',ja:'現在のブランド'" in response.text
    assert "/site-assets/icons/plus.svg" in response.text
    assert "const ADMIN_MODULES = [" in response.text
    assert "{route:'engines',label:{zh:'AI 可见性'" in response.text
    assert "{route:'channels',label:{zh:'引用来源',en:'Citation sources'" in response.text
    assert "{route:'engine-settings',label:{zh:'模型与测量',en:'Models and measurement'" in response.text
    assert "{route:'publishing',label:{zh:'发布目的地',en:'Publishing destinations'" in response.text
    assert "{route:'overview',label:{zh:'品牌概览'" in response.text
    assert "{route:'project-settings',label:{zh:'品牌管理'" in response.text
    assert "/site-assets/icons/layout-dashboard.svg" in response.text
    assert 'id="nav-scrim"' in response.text
    assert '@media (min-width:900px) and (max-width:1199px)' in response.text
    assert '@media (max-width:899px)' in response.text
    assert "const rawFetch = window.fetch.bind(window)" in response.text
    assert "labels:{zh:'智谱 GLM',en:'Zhipu AI GLM'" in response.text
    assert "labels:{zh:'百度 AI 搜索',en:'Baidu AI Search'" in response.text
    assert "function localizedModelLabel(model, fallback)" in response.text
    assert "label:localizedModelLabel(k)" in response.text
    assert "window.disvoraiModelLabel(item.engine_code, item.engine_name || item.engine_code)" in response.text
    assert "'智谱GLM':'Zhipu AI GLM'" in response.text
    assert "'豆包(方舟API)':'Doubao Ark API'" in response.text
    assert "'豆包 App / 网页版（与方舟 API 结果不同，需分开采）':'Doubao app / web (measured separately from Ark API)'" in response.text
    assert "'认证模式':'Authentication mode'" in response.text
    assert "'登录后查看项目报告，或创建一个新的工作区。':'Sign in to view project reports or create a new workspace.'" in response.text
    assert "'邮箱或密码不正确。':'Incorrect email or password.'" in response.text
    assert "['下载失败：','Download failed: ']" in response.text
    assert "['仅所有者可配置 API Key','Only owners can configure API keys']" in response.text
    assert "'统一一句话定义，四处逐字一致':'Standardize the one-sentence definition across four surfaces'" in response.text
    assert "['实体消歧','Entity disambiguation']" in response.text
    assert "function playbookLocalized(value)" in response.text
    assert "playbookLocalized(task.package || '')" in response.text
    assert "function uiText(value)" in response.text
    assert "const engineOnboard = vOnboard" in response.text
    assert "Two sampling rounds are required" in response.text
    assert "No competitor data yet. Configure competitors in Settings, then run a full cycle." in response.text
    assert "API · Model knowledge · API key required" in response.text
    assert "setTimeout(function () { uiTranslate(document.body); }, 0)" in response.text
    assert "const engineFactsView = vFacts" in response.text
    assert "Not compared — log this in Gap Diagnosis · Fact deviations" in response.text
    assert "/api/v1/projects" in response.text
    assert "/api/v1/settings/keys" in response.text
    assert "disvorai_access_token" in response.text
    assert "job.status === 'queued' ? 'running'" in response.text
    assert "skip_llm:configuredKeyCount === 0" in response.text
    assert "document.querySelector('#ob-nosample')?.checked" in response.text
    assert "name:body.name || null" in response.text
    assert "url:body.url, name:body.name || null, skip_llm:" in response.text
    assert "market:body.market" not in response.text
    assert 'name="obm"' not in response.text
    assert 'name="cmkt"' not in response.text
    assert "const mkNeed=" not in response.text
    assert "已配置引擎：${okCn+okGl} 个" in response.text
    assert "cfg.market='both'" in response.text
    assert "${mktLabel(x.market)} ·" not in response.text
    assert "${mktLabel(k.market)}" not in response.text
    assert "中文题只问国内引擎" not in response.text
    assert "英文题只问海外引擎" not in response.text
    assert "国内" not in response.text
    assert "海外" not in response.text
    assert "中文市场" not in response.text
    assert "英文市场" not in response.text
    assert "中文引擎" not in response.text
    assert "英文引擎" not in response.text
    assert "CN ($1) and Global ($2)" not in response.text
    assert "中国（$1 件）と" not in response.text
    assert "语言路由：中文题匹配中文回答能力" in response.text
    assert "const mktLabel=m=>m==='cn'?'中文':m==='global'?'英文':'通用';" in response.text
    assert "['中文','Chinese'],['英文','English']" in response.text
    assert "data.job.log_offset || requested" in response.text
    assert "/api/v1/projects/actions" in response.text
    assert "'/actions/' + encodeURIComponent(action)" in response.text
    assert "if (action === 'serve') action = 'sample'" not in response.text
    assert "'/config'" in response.text
    assert "'/assets'" in response.text
    assert "'/workbench?qid='" in response.text
    assert "'/questions'" in response.text
    assert "创建外部协作任务" in response.text
    assert "创建 Offsite 工单" not in response.text
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
    assert "人工 · 产品端核验" in response.text
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
    assert "function competitorDiscoveryPanel()" in response.text
    assert "D.competitor_discovery" in response.text
    assert "自动发现竞品" in response.text
    assert "待采样确认" in response.text
    assert "采样已确认" in response.text
    assert "Discovered competitors" in response.text
    assert "自動検出した競合" in response.text
    assert "竞品候选等待采样" in response.text
    assert "AI 如何描述你" in response.text
    assert "基于品牌被实际提及的回答短语，词频按样本去重。" in response.text
    assert "品牌印象加载失败，请刷新后重试。" in response.text
    assert "同一批无提示采样共 ${Number(NS.cn||0)+Number(NS.global||0)} 条有效样本" in response.text
    assert "来源：百度与 Google 搜索建议" in response.text
    assert "这是前端渲染站点常见的致命问题" in response.text
    assert "分母为该语言组" in response.text
    assert "全部有效样本口径" in response.text
    assert "原文证据" in response.text
    assert "/api/v1/team/members" in response.text
    assert "/api/v1/team/invitations" in response.text
    assert "/api/v1/auth/switch-tenant" in response.text
    assert "invitation_token:invitationToken" in response.text
    assert "function teamPanel()" in response.text
    assert "function teamInviteModal()" in response.text
    assert "VIEWS.settings=vLegacySettings" in response.text
    assert "VIEWS['project-settings']=vProjectSettings" in response.text
    assert "VIEWS.automation=vAutomation" in response.text
    assert "VIEWS.archive=vArchive" in response.text
    assert "VIEWS['engine-settings']=vEngineSettings" in response.text
    assert "VIEWS.integrations=vIntegrations" in response.text
    assert "VIEWS.outreach=vOutreach" in response.text
    assert "VIEWS.publishing=vPublishing" in response.text
    assert "VIEWS.branding=vBranding" in response.text
    assert "VIEWS.team=vTeam" in response.text
    assert "VIEWS.billing=vBilling" in response.text
    assert "VIEWS.security=vSecurity" in response.text
    assert "const panels = billingPanel()" not in response.text
    assert "history.replaceState({r:R,engSel:ST.engSel,gapTab:ST.gapTab},'','#project-settings')" in response.text
    assert "onclick=\"go('engine-settings')\">去配置 Key" in response.text
    assert "closeModal();go('publishing')\">渠道配置" in response.text
    assert "管理品牌清单、官网域名和竞品范围。':'Manage brands" in response.text
    assert "管理品牌清单、官网域名和竞品范围。':'ブランド、公式サイト" in response.text
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
    assert "API · 联网检索" in response.text
    assert "API · 模型内知识" in response.text
    assert "Models and measurement" in response.text
    assert "Measurement usage" in response.text
    assert "Managed usage" in response.text
    assert "CNY " in response.text
    assert "WeChat Official Account drafts" in response.text
    assert "WeChat Official Account and WordPress create drafts only" in response.text
    assert "本月费用" in response.text
    assert "费用信息加载失败" in response.text
    assert "仅所有者可更改" in response.text
    assert "缺少 BYOK 的模型将按页面所示单价逐次收费" in response.text
    assert "const enginePlanView = vPlan" in response.text
    assert "function playbookMatrix(tasks)" in response.text
    assert "function sortedPlaybookTasks(tasks)" in response.text
    assert "影响优先级 × 工作量" in response.text
    assert "未分类任务" in response.text
    assert "VIEWS.plan = vPlan" in response.text
    assert "grid-template-columns:104px repeat(3,minmax(218px,1fr))" in response.text
    assert "playbook-matrix-scroll" in response.text
    assert "アクションプラン表示" in response.text
    assert 'class="settings-core-grid"' in response.text
    assert ".settings-core-grid{grid-template-columns:1fr!important}" in response.text
    assert "/api/v1/sso/config" in response.text
    assert "/api/v1/sso/audit-events" in response.text
    assert "function ssoPanel()" in response.text
    assert "function saveSsoConfiguration()" in response.text
    assert "控制措施已就绪，未获得 SOC 2 认证。" in response.text
    assert "controls_ready_not_certified" in response.text
    assert "Technical controls are ready; DisvorAI is not SOC 2 certified." in response.text
    assert "技術的統制は準備済みですが、DisvorAI は SOC 2 認証を取得していません。" in response.text
    assert ".sso-form-grid{grid-template-columns:1fr}" in response.text
    assert ".sso-section-title{padding-left:20px" in response.text
    assert "/api/v1/integrations/semrush" in response.text
    assert "'/integrations/' + encodeURIComponent(body.provider) + '/sync'" in response.text
    assert "function integrationPanel()" in response.text
    assert "function syncIntegration(provider)" in response.text
    assert "Google Search Console" in response.text
    assert "自然搜索与站点表现" in response.text
    assert ".integration-grid{grid-template-columns:1fr}" in response.text
    assert ".integration-section-title{padding-left:20px" in response.text
    assert "base + '/drafts/' + encodeURIComponent(body.draft_id) + '/send'" in response.text
    assert "function outreachPanel()" in response.text
    assert "function outreachSendReview(draft)" in response.text
    assert "confirmation_text:text" in response.text
    assert "SEND '+draftId" in response.text
    assert "我已核对收件人、主题和正文" in response.text
    assert "人工确认发送" in response.text
    assert ".outreach-section-title{padding-left:20px" in response.text
    assert ".outreach-smtp-grid,.outreach-identity-grid{grid-template-columns:1fr!important}" in response.text
    assert ".settings-section-subtitle{padding-left:20px}" in response.text
    assert "white-space:pre-wrap;overflow-wrap:anywhere" in response.text
    assert "/api/v1/billing/subscribe" in response.text
    assert "function billingPanel()" in response.text
    assert "function setBillingInterval(value)" in response.text
    assert "Stripe 尚未配置，当前不能发起真实付款" in response.text
    assert "window.location.assign(result.checkout_url)" in response.text
    assert "const billingStatusLabel" in response.text
    assert "BILLING_STATE=null;toast('订阅已更新')" not in response.text
    assert "BILLING_ANNUAL_DISCOUNT_PERCENT" not in response.text
    assert "年付优惠" in response.text
    assert ".billing-plan-grid{grid-template-columns:1fr}" in response.text
    assert "base + '/' + encodeURIComponent(body.archive_id) + '/restore'" in response.text
    assert "function archivePanel()" in response.text
    assert "function restoreArchiveModal(archiveId)" in response.text
    assert "confirmation_text:text" in response.text
    assert "RESTORE '+archiveId" in response.text
    assert "${uiText('活动数据源')} · ${uiText('本地文件系统')}" in response.text
    assert ".archive-row{grid-template-columns:1fr auto" in response.text
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


def test_ui_compatibility_route_remains_available():
    response = TestClient(app).get("/ui")

    assert response.status_code == 200
    assert "DisvorAI" in response.text


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
    assert client.get("/files/second-project/delivery/2026-07-31/index.html").status_code == 404

    client.cookies.clear()
    assert client.get("/files/first-project/delivery/2026-07-31/index.html").status_code == 401
