import re
from pathlib import Path

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
    assert '<script type="module" src="/app/app.js' in response.text
    assert '/app/app.js?v=3.8' in response.text
    assert "/site-assets/styles/tokens.css" in response.text
    assert "/site-assets/styles/base.css" in response.text
    assert "/site-assets/styles/components.css" in response.text
    assert "/site-assets/styles/app.css?v=3.3" in response.text
    assert '<script src="/site-assets/theme-init.js"></script>' in response.text
    assert re.search(r"<script(?![^>]*\bsrc=)[^>]*>", response.text, re.IGNORECASE) is None
    policy = response.headers["content-security-policy"]
    assert "script-src 'self';" in policy
    assert "script-src 'self' 'unsafe-inline'" not in policy


def test_spa_static_modules_are_served():
    client = TestClient(app)
    for path in (
        "/app/app.js",
        "/app/api.js",
        "/app/i18n.js",
        "/app/safe-html.js",
        "/app/views/overview.js",
        "/app/views/engines.js",
        "/app/views/plan.js",
        "/app/views/report.js",
        "/app/views/siteaudit.js",
        "/app/views/facts.js",
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


def test_citation_sources_view_has_no_legacy_seo_integrations():
    client = TestClient(app)
    channels = client.get("/app/views/channels.js").text
    app_js = client.get("/app/app.js").text
    api_js = client.get("/app/api.js").text

    assert "AI Citation Sources" in channels
    assert "Run Citation Sampling" in channels
    assert "TabAPI" not in channels
    assert "getProjectTraffic" not in channels
    assert "SEO Integrations" not in app_js
    assert "views/integrations.js" not in app_js
    assert "getProjectTraffic" not in api_js
    assert client.get("/app/views/integrations.js").status_code == 404


def test_legacy_seo_integration_api_is_not_exposed():
    client = TestClient(app)

    assert client.get("/api/v1/integrations").status_code == 404
    assert client.get(
        "/api/v1/integrations/search-console/authorize",
        params={"project_id": 1},
    ).status_code == 404
    assert client.post("/api/v1/projects/1/integrations/tabapi/sync").status_code == 404


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


def test_api_js_uses_cookie_session_refresh_and_unwraps_collections():
    text = TestClient(app).get("/app/api.js").text

    assert "'X-CiteAura-Session': 'cookie'" in text
    assert "'X-CiteAura-Session': '1'" not in text
    assert "let refreshPromise = null" in text
    assert "refreshSubscribers" not in text
    assert "_authRetried: true" in text
    for field in ("jobs", "tickets", "members", "invitations", "schedule", "keys", "history", "deliveries", "events", "archives"):
        assert f"'{field}'" in text


def test_frontend_contracts_match_backend_request_models():
    root = Path(__file__).resolve().parents[2]
    reset = (root / "web/app/views/auth-reset.js").read_text("utf-8")
    invite = (root / "web/app/views/auth-invite.js").read_text("utf-8")
    plan = (root / "web/app/views/plan.js").read_text("utf-8")
    engines = (root / "web/app/views/engine-settings.js").read_text("utf-8")
    automation = (root / "web/app/views/automation.js").read_text("utf-8")
    publishing = (root / "web/app/views/publishing.js").read_text("utf-8")
    outreach = (root / "web/app/views/outreach.js").read_text("utf-8")
    billing = (root / "web/app/views/billing.js").read_text("utf-8")
    overview = (root / "web/app/views/overview.js").read_text("utf-8")
    onboarding = (root / "web/app/views/onboarding.js").read_text("utf-8")
    telemetry = (root / "web/app/components/telemetry-modal.js").read_text("utf-8")
    siteaudit = (root / "web/app/views/siteaudit.js").read_text("utf-8")
    facts = (root / "web/app/views/facts.js").read_text("utf-8")

    assert "resetPassword({ token, password })" in reset
    assert "preview.tenant?.name" in invite
    assert "invitation_token: token" in invite
    assert "{ url, ask_text, influenced_questions }" in plan
    assert "{ code: 'openai'" in engines
    assert "Testing endpoint, API Key, and Model ID..." in engines
    assert "provider_http_401" in engines
    assert "audit.applicable_avg_score" in siteaudit
    assert "audit.presentation_version" in siteaudit
    assert "p.applicable_score" in siteaudit
    assert "p.issues.map" not in siteaudit
    assert "escapeHtml(facts.text || '')" in facts
    assert "manual_translation_required" in facts
    assert "evidence_rebuilt" in facts
    catalog = (root / "api/i18n/messages/en.json").read_text("utf-8")
    assert '"siteaudit.overall_score": "Applicable Technical Score"' in catalog
    assert '"siteaudit.col_issues": "Applicable Findings"' in catalog
    assert "await ctx.reloadCurrentView()" in engines
    assert "ctx.navigate('#/engine-settings')" not in engines
    assert 'id="supported-model-endpoints"' in engines
    assert 'data-provider-kind="custom"' in engines
    assert "Third-party / OpenAI-compatible" in engines
    assert "Custom OpenAI-Compatible Providers" not in engines
    assert 'option value="1"' not in automation
    assert "{ config, credentials }" in publishing
    assert "revision," in outreach and "confirmed: true" in outreach
    assert "{ plan, billing_interval: currentInterval }" in billing
    assert "plansData.payment?.enabled" in billing
    assert "can_upgrade" in billing
    assert "activeSubscription" in billing
    assert "Switch to ${label" in billing
    assert "Upgrade to Pro" in billing
    assert "no need to wait" in billing
    assert "project.questions" in overview
    assert 'href="#/questions"' in overview
    assert "project_questions_required" in overview
    assert "isGeneratingQuestions" in overview
    assert "project.project?.status || project.status" in overview
    assert "Generating Questions..." in overview
    assert 'id="btn-rerun-autopilot"' in overview
    assert "projects.estimateSample(projectId)" in overview
    assert "projects.triggerAction(projectId, 'autopilot'" in overview
    assert "ctx.openTelemetry(res.job_id, 'autopilot'" in overview
    assert "Manually maintained action tickets are preserved" in overview
    assert "ctx.openTelemetry(res.job_id" in onboarding
    assert "res.action || (skip_llm ? 'bootstrap' : 'autopilot')" in onboarding
    assert "onComplete: async ()" in onboarding
    assert "STAGE_MAP" in telemetry
    assert "Crawl Website" in telemetry
    assert "Verification & Delivery Pack" in telemetry
    assert "Current activity" in telemetry
    assert "retry?.job_id || retry?.job?.id" in telemetry
    assert "Math.floor((boundedProgress / 100) * steps.length)" in telemetry
    app_js = (root / "web/app/app.js").read_text("utf-8")
    assert "citeaura_intent_plan" in app_js
    assert "ENTRY_PLANS" in app_js
    assert "engine-settings.js?v=2.8" in app_js
    assert "engines.js?v=2.6" in app_js
    assert "workbench.js?v=2.6" in app_js
    assert "overview.js?v=2.7" in app_js
    assert "onboarding.js?v=2.6" in app_js
    assert "facts.js?v=2.6" in app_js
    assert "telemetry-modal.js?v=2.6" in app_js
    assert "function projectKey(project)" in app_js
    assert "projectKey(p) === state.activeProjectId" in app_js
    assert "const renderId = ++renderSequence" in app_js
    assert "renderId !== renderSequence" in app_js
    assert "|| state.projectsList[0]" not in app_js

    engines = (root / "web/app/views/engines.js").read_text("utf-8")
    assert "Project response mismatch" in engines
    assert "Sample response project mismatch" in engines


def test_dynamic_html_uses_sanitized_entry_points_and_no_inline_handlers():
    root = Path(__file__).resolve().parents[2]
    app_js = (root / "web/app/app.js").read_text("utf-8")
    modal_js = (root / "web/app/components/modal.js").read_text("utf-8")
    sanitizer = (root / "web/app/safe-html.js").read_text("utf-8")

    assert "setSafeHtml(appRoot" in app_js
    assert "setSafeHtml(viewContainer" in app_js
    assert "setSafeHtml(box" in modal_js
    assert "name.startsWith('on')" in sanitizer
    assert "URL_ATTRIBUTES" in sanitizer
    assert "'script', 'style', 'iframe'" in sanitizer
    assert "window.clearInterval(jobPollingTimer)" in app_js
    for path in (root / "web").rglob("*"):
        if path.suffix in (".html", ".js"):
            assert re.search(r"\bon(?:click|error|load)\s*=", path.read_text("utf-8"), re.IGNORECASE) is None


def test_ui_compatibility_route_remains_available():
    response = TestClient(app).get("/ui")

    assert response.status_code == 200
    assert "CiteAura" in response.text
    assert '<script type="module" src="/app/app.js' in response.text


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
