import json
import re
import shutil
import subprocess
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
    assert '<script type="module" src="/app-assets/app.js' in response.text
    assert '<script type="module" src="/app-assets/app.js"></script>' in response.text
    assert "/site-assets/styles/tokens.css" in response.text
    assert "/site-assets/styles/base.css" in response.text
    assert "/site-assets/styles/components.css" in response.text
    assert "/site-assets/styles/app.css" in response.text
    assert '<script src="/runtime-assets/theme-init.js"></script>' in response.text
    assert re.search(r"<script(?![^>]*\bsrc=)[^>]*>", response.text, re.IGNORECASE) is None
    policy = response.headers["content-security-policy"]
    assert "script-src 'self';" in policy
    assert "script-src 'self' 'unsafe-inline'" not in policy
    assert response.headers["cache-control"] == "private, no-store, max-age=0"


def test_public_trailing_slash_redirect_uses_configured_canonical_url(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://citeaura.example")

    response = TestClient(app).get("/docs/?utm_source=search", follow_redirects=False)

    assert response.status_code == 308
    assert response.headers["location"] == "https://citeaura.example/docs?utm_source=search"


def test_private_application_trailing_slash_is_not_publicly_redirected():
    response = TestClient(app).get("/app/", follow_redirects=False)

    assert response.status_code == 200
    assert "Location" not in response.headers


def test_admin_shell_is_excluded_from_search_index():
    response = TestClient(app).get("/admin/index.html")

    assert response.status_code == 200
    assert '<meta name="robots" content="noindex, nofollow">' in response.text


def test_spa_static_modules_are_served():
    client = TestClient(app)
    for path in (
        "/app-assets/app.js",
        "/app-assets/api.js",
        "/app-assets/i18n.js",
        "/app-assets/safe-html.js",
        "/app-assets/views/overview.js",
        "/app-assets/views/engines.js",
        "/app-assets/views/plan.js",
        "/app-assets/views/report.js",
        "/app-assets/views/siteaudit.js",
        "/app-assets/views/facts.js",
        "/app-assets/views/onboarding.js",
        "/app-assets/components/toast.js",
        "/app-assets/components/modal.js",
        "/app-assets/components/badge.js",
        "/app-assets/components/kpi.js",
        "/app-assets/components/table.js",
        "/app-assets/components/tabs.js",
    ):
        response = client.get(path)
        assert response.status_code == 200, f"Failed to serve {path}"
        assert "javascript" in response.headers["content-type"].lower() or "text/" in response.headers["content-type"].lower()
        assert response.headers["cache-control"] == "private, no-store, max-age=0"


def test_admin_shell_assets_are_uncached():
    client = TestClient(app)
    for path in ("/admin/admin.js", "/admin/admin.css"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["cache-control"] == "private, no-store, max-age=0"


def test_spa_uses_one_uncached_module_namespace():
    """Keep every SPA module on the same stable URL and cache contract."""
    root = Path(__file__).resolve().parents[2]
    client = TestClient(app)
    shell = client.get("/app")

    assert '<script type="module" src="/app-assets/app.js"></script>' in shell.text
    assert re.search(r'<script[^>]+src="/app/(?:[^"?]+\.js)', shell.text) is None

    module_files = sorted((root / "web" / "app").rglob("*.js"))
    assert module_files
    for path in module_files:
        relative = path.relative_to(root / "web" / "app").as_posix()
        response = client.get(f"/app-assets/{relative}")
        assert response.status_code == 200, relative
        assert response.headers["cache-control"] == "private, no-store, max-age=0"
        source = path.read_text("utf-8")
        imports = re.findall(r"(?:\bfrom\s+|\bimport\s*\()\s*['\"]([^'\"]+)['\"]", source)
        assert all("?" not in spec for spec in imports), relative
        assert all(not spec.startswith("/app/") for spec in imports), relative

    # Keep old direct module URLs readable for bookmarks, but never cache them.
    legacy = client.get("/app/app.js")
    assert legacy.status_code == 200
    assert legacy.headers["cache-control"] == "private, no-store, max-age=0"


def test_frontend_interactive_controls_have_explicit_runtime_contracts():
    """Prevent sanitizer/cache fixes from hiding unbound controls in new views."""
    root = Path(__file__).resolve().parents[2]
    button_pattern = re.compile(r"<button\b([^>]*)>", re.IGNORECASE | re.DOTALL)
    form_pattern = re.compile(r"<form\b", re.IGNORECASE)

    for path in sorted((root / "web" / "app").rglob("*.js")):
        source = path.read_text("utf-8")
        buttons = button_pattern.findall(source)
        if not buttons and not form_pattern.search(source):
            continue

        for attrs in buttons:
            assert re.search(r"\btype\s*=\s*['\"](?:button|submit|reset)['\"]", attrs, re.IGNORECASE), path
            assert re.search(r"\bon(?:click|change|submit|error|load)\s*=", attrs, re.IGNORECASE) is None, path

        has_click_binding = bool(re.search(r"addEventListener\(\s*['\"]click['\"]", source))
        has_submit_binding = bool(re.search(r"addEventListener\(\s*['\"]submit['\"]", source))
        if buttons:
            assert has_click_binding or has_submit_binding, path
        if form_pattern.search(source):
            assert has_submit_binding, path


def test_frontend_view_modules_parse_as_es_modules():
    """Import every view as an ES module so nested template syntax is parsed."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")

    root = Path(__file__).resolve().parents[2]
    modules = sorted((root / "web" / "app" / "views").glob("*.js"))
    imports = ",".join(f"import({module.as_uri()!r})" for module in modules)
    result = subprocess.run(
        [node, "--input-type=module", "-e", f"await Promise.all([{imports}]);"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_citation_sources_view_has_no_legacy_seo_integrations():
    client = TestClient(app)
    channels = client.get("/app-assets/views/channels.js").text
    app_js = client.get("/app-assets/app.js").text
    api_js = client.get("/app-assets/api.js").text

    assert "AI Citation Sources" in channels
    assert "Run Citation Sampling" in channels
    assert "External evidence records" in channels
    assert "addExternalEvidence" in channels
    assert "import { projects, workspace } from '../api.js';" in channels
    assert "workspace.getExternalEvidence(projectId)" in channels
    assert "workspace.addExternalEvidence(ctx.activeProjectId" in channels
    assert "projects.getExternalEvidence" not in channels
    assert "projects.addExternalEvidence" not in channels
    assert "TabAPI" not in channels
    assert "getProjectTraffic" not in channels
    assert "SEO Integrations" not in app_js
    assert "views/integrations.js" not in app_js
    assert "getProjectTraffic" not in api_js
    assert client.get("/app-assets/views/integrations.js").status_code == 404


def test_action_tickets_are_listed_in_execution_navigation():
    app_js = TestClient(app).get("/app-assets/app.js").text

    assert "defaultView: 'assets'" in app_js
    assert "{ id: 'plan', labelKey: 'nav.plan', defaultLabel: 'Action Tickets' }" in app_js
    assert "hidden: true" not in app_js.split("labelKey: 'nav.plan'")[1].split("},", 1)[0]


def test_legacy_seo_integration_api_is_not_exposed():
    client = TestClient(app)

    assert client.get("/api/v1/integrations").status_code == 404
    assert client.get(
        "/api/v1/integrations/search-console/authorize",
        params={"project_id": 1},
    ).status_code == 404
    assert client.post("/api/v1/projects/1/integrations/tabapi/sync").status_code == 404


def test_api_js_covers_all_core_endpoints():
    response = TestClient(app).get("/app-assets/api.js")
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
    text = TestClient(app).get("/app-assets/api.js").text

    assert "'X-CiteAura-Session': 'cookie'" in text
    assert "'X-CiteAura-Session': '1'" not in text
    assert "let refreshPromise = null" in text
    assert "refreshSubscribers" not in text
    assert "_authRetried: true" in text
    assert "retryLoginTransport" in text
    for field in ("jobs", "tickets", "members", "invitations", "schedule", "keys", "history", "deliveries", "archives"):
        assert f"'{field}'" in text


def test_spa_auth_routes_enforce_session_state_contract():
    root = Path(__file__).resolve().parents[2]
    app_js = (root / "web/app/app.js").read_text("utf-8")
    login_js = (root / "web/app/views/auth-login.js").read_text("utf-8")
    register_js = (root / "web/app/views/auth-register.js").read_text("utf-8")

    assert "const AUTH_ENTRY_ROUTES = new Set(['login', 'register'])" in app_js
    assert "auth-login.js" in app_js
    assert "auth-register.js" in app_js
    assert re.search(r"\blite\b", app_js, re.IGNORECASE) is None
    assert "if (!state.sessionChecked)" in app_js
    assert "AUTH_ENTRY_ROUTES.has(route) && state.user" in app_js
    assert "state.clearSession();" in app_js
    assert "session_establishment_failed" in app_js
    assert login_js.index("await ctx.reloadSession()") < login_js.index("auth.login_success")
    assert register_js.index("await ctx.reloadSession()") < register_js.index("auth.register_success")


def test_landing_auth_calls_to_action_use_explicit_routes():
    html = TestClient(app).get("/").text

    assert 'class="nav-sign-in" href="/app?auth=login"' in html
    assert html.count('href="/app?auth=register"') == 4
    assert re.search(r'href="/app"[^>]*>Start (?:free|14-day) trial', html) is None


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
    assets = (root / "web/app/views/assets.js").read_text("utf-8")
    report = (root / "web/app/views/report.js").read_text("utf-8")

    assert re.search(r"\blite\b", billing, re.IGNORECASE) is None

    assert "resetPassword({ token, password })" in reset
    assert "preview.tenant?.name" in invite
    assert "invitation_token: token" in invite
    assert "{ url, ask_text, influenced_questions }" in plan
    assert "{ code: 'openai'" in engines
    assert "engine_settings.testing_status" in engines
    from api.i18n.catalog import load_all_catalogs
    assert "provider_http_401" in load_all_catalogs()["en"]
    assert "audit.applicable_avg_score" in siteaudit
    assert "audit.presentation_version" in siteaudit
    assert "p.applicable_score" in siteaudit
    assert "p.issues.map" not in siteaudit
    assert "escapeHtml(facts.text || '')" in facts
    assert "manual_translation_required" in facts
    assert "evidence_rebuilt" in facts
    assert "facts-approve" in facts
    assert "approve" in facts
    assert "machine_verified" in facts
    assert "official-site crawl" in facts
    assert "derived asset(s) cannot be published" in assets
    assert "derived_from_unreviewed_brand_facts" not in assets
    assert "Campaign Proposals" in assets
    assert "campaign_proposals" in assets
    assert "ctx.params?.question" in assets
    assert "Impact remains a hypothesis" in assets
    assert "Publication always requires human approval" in assets
    assert "escapeHtml(first.text || '')" in assets
    assert "Download diagnostic ZIP" in report
    assert "Download review ZIP" in report
    assert "Diagnostic pack ready" in report
    assert "Implementation pack ready" in report
    catalog = (root / "api/i18n/messages/en.json").read_text("utf-8")
    assert '"siteaudit.overall_score": "Applicable Technical Score"' in catalog
    assert '"siteaudit.col_issues": "Applicable Findings"' in catalog
    assert "await ctx.reloadCurrentView()" in engines
    assert "ctx.navigate('#/engine-settings')" not in engines
    assert 'id="supported-model-endpoints"' in engines
    assert 'data-provider-kind="custom"' in engines
    assert "Third-party / OpenAI-compatible" in engines
    assert "Custom OpenAI-Compatible Providers" not in engines
    assert 'option value="1"' in automation
    assert "Daily (1 Day)" in automation
    assert "{ config, credentials }" in publishing
    assert "revision," in outreach and "confirmed: true" in outreach
    assert "{ plan, billing_interval: currentInterval }" in billing
    assert "plansData.payment?.enabled" in billing
    assert "can_upgrade" in billing
    assert "activeSubscription" in billing
    assert "Switch to ${planName" in billing
    assert "Upgrade to Pro" in billing
    assert "no need to wait" in billing
    assert "Activation progress" in billing
    assert "Platform-pool calls" in billing
    assert "project.questions" in overview
    assert 'href="#/questions"' in overview
    assert "project_questions_required" in overview
    assert "isGeneratingQuestions" in overview
    assert "project.project?.status || project.status" in overview
    assert "Generating Questions..." in overview
    assert 'id="btn-rerun-autopilot"' in overview
    assert "projects.triggerSampleGaps(projectId)" in overview
    assert "projects.triggerSample(projectId)" not in overview
    assert "projects.estimateSample(projectId)" in overview
    assert "projects.triggerAction(projectId, 'autopilot'" in overview
    assert "ctx.openTelemetry(res.job_id, 'autopilot'" in overview
    assert "Manually maintained action tickets are preserved" in overview
    assert "ctx.openTelemetry(res.job_id" in onboarding
    assert "res.action || (no_sample ? 'bootstrap' : 'autopilot')" in onboarding
    assert "projects.preflight" in onboarding
    assert "no_sample" in onboarding
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
    assert "engine-settings.js" in app_js
    assert "engines.js" in app_js
    assert "workbench.js" in app_js
    assert "overview.js" in app_js
    assert "onboarding.js" in app_js
    assert "facts.js" in app_js
    assert "telemetry-modal.js" in app_js
    assert "function projectKey(project)" in app_js
    assert "projectKey(p) === state.activeProjectId" in app_js
    assert "const renderId = ++renderSequence" in app_js
    assert "renderId !== renderSequence" in app_js
    assert "|| state.projectsList[0]" not in app_js

    engines = (root / "web/app/views/engines.js").read_text("utf-8")
    assert "Project response mismatch" in engines
    assert "Sample response project mismatch" in engines
    assert "flex-wrap:wrap;min-width:0;" in engines
    assert "escapeHtml(s.platform_name || s.platform || t('engines.ai_model', {}, 'AI Model'))" in engines


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
    blocked_tags = sanitizer.split('const INTERACTIVE_TAGS', 1)[0]
    for interactive_tag in ("'form'", "'input'", "'button'", "'select'", "'textarea'"):
        assert interactive_tag not in blocked_tags
    assert "BLOCKED_TAGS.has(tag) && !INTERACTIVE_TAGS.has(tag)" in sanitizer
    for path in (root / "web" / "app").rglob("*.js"):
        text = path.read_text("utf-8")
        assert re.search(r"(?:from\s+|import\()['\"][^'\"]+\?v=", text) is None, path
    assert "window.clearInterval(jobPollingTimer)" in app_js
    for path in (root / "web").rglob("*"):
        if path.suffix in (".html", ".js"):
            assert re.search(r"\bon(?:click|error|load)\s*=", path.read_text("utf-8"), re.IGNORECASE) is None


def test_app_view_content_uses_outer_shell_as_the_vertical_scroll_container():
    root = Path(__file__).resolve().parents[2]
    app_css = (root / "web/assets/styles/app.css").read_text("utf-8")
    view_rule = app_css.split(".app-view-container {", 1)[1].split("}", 1)[0]

    assert "flex: 0 0 auto;" in view_rule
    assert "min-height: 100%;" in view_rule
    assert "overflow: visible;" in view_rule


def test_ui_compatibility_route_remains_available():
    response = TestClient(app).get("/ui")

    assert response.status_code == 200
    assert "CiteAura" in response.text
    assert '<script type="module" src="/app-assets/app.js' in response.text


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
    assert client.post(
        "/api/v1/auth/register",
        json={"email": "first@example.com", "password": "correct-horse-battery", "tenant_name": "tenant-a"},
    ).status_code == 202
    assert client.post(
        "/api/v1/auth/register",
        json={"email": "second@example.com", "password": "correct-horse-battery", "tenant_name": "tenant-b"},
    ).status_code == 202

    def _tenant_id(email):
        # 注册响应不再返回 tenant，工作区信息统一从 /me 读取。
        login = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "correct-horse-battery"},
        )
        assert login.status_code == 200
        current = client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )
        assert current.status_code == 200
        return current.json()["tenant"]["id"]

    first_tenant_id = _tenant_id("first@example.com")
    second_tenant_id = _tenant_id("second@example.com")
    with session_factory() as db:
        db.add_all([
            Project(tenant_id=first_tenant_id, slug="first-project", url="https://first.example", market="both"),
            Project(tenant_id=second_tenant_id, slug="second-project", url="https://second.example", market="both"),
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

def test_workspace_ui_preserves_evidence_semantics():
    root = Path(__file__).resolve().parents[2]
    overview = (root / "web/app/views/overview.js").read_text("utf-8")
    engines = (root / "web/app/views/engines.js").read_text("utf-8")
    plan = (root / "web/app/views/plan.js").read_text("utf-8")
    verify = (root / "web/app/views/verify.js").read_text("utf-8")
    report = (root / "web/app/views/report.js").read_text("utf-8")
    app_js = (root / "web/app/app.js").read_text("utf-8")
    channels = (root / "web/app/views/channels.js").read_text("utf-8")
    siteaudit = (root / "web/app/views/siteaudit.js").read_text("utf-8")
    assets = (root / "web/app/views/assets.js").read_text("utf-8")
    competitors = (root / "web/app/views/competitors.js").read_text("utf-8")
    questions = (root / "web/app/views/questions.js").read_text("utf-8")
    facts = (root / "web/app/views/facts.js").read_text("utf-8")
    blueprint = (root / "web/app/views/blueprint.js").read_text("utf-8")
    team = (root / "web/app/views/team.js").read_text("utf-8")
    billing = (root / "web/app/views/billing.js").read_text("utf-8")
    engine_settings = (root / "web/app/views/engine-settings.js").read_text("utf-8")
    archive = (root / "web/app/views/archive.js").read_text("utf-8")
    outreach = (root / "web/app/views/outreach.js").read_text("utf-8")
    publishing = (root / "web/app/views/publishing.js").read_text("utf-8")
    project_settings = (root / "web/app/views/project-settings.js").read_text("utf-8")
    automation = (root / "web/app/views/automation.js").read_text("utf-8")
    entities = (root / "web/app/views/entities.js").read_text("utf-8")
    workbench = (root / "web/app/views/workbench.js").read_text("utf-8")
    auth_forgot = (root / "web/app/views/auth-forgot.js").read_text("utf-8")
    auth_reset = (root / "web/app/views/auth-reset.js").read_text("utf-8")
    auth_invite = (root / "web/app/views/auth-invite.js").read_text("utf-8")
    auth_register = (root / "web/app/views/auth-register.js").read_text("utf-8")
    onboarding = (root / "web/app/views/onboarding.js").read_text("utf-8")
    gaps = (root / "web/app/views/gaps.js").read_text("utf-8")
    branding_view = (root / "web/app/views/branding.js").read_text("utf-8")
    landing_css = (root / "web/assets/styles/landing.css").read_text("utf-8")
    theme_init = (root / "web/assets/theme-init.js").read_text("utf-8")

    assert "[DEMO · SYNTHETIC BASELINE]" not in overview
    assert "overview.cohort_none" in overview
    assert "overview.kpi_denominator" in overview
    assert 'id="btn-run-sample" class="btn btn-secondary btn-sm"' in overview
    assert "activeJob || isViewer" in overview
    assert 'id="btn-run-verify" class="btn btn-secondary btn-sm"' in overview

    assert "Median position" in engines and "Avg Rank" not in engines
    assert "engines.no_source_urls" in engines
    assert "ctx.role === 'viewer'" in plan
    assert "plan.viewer_read_only" in plan
    assert "verify.technical_only" in verify and "activeJob" in verify
    assert "report.readiness_unavailable" in report and "activeJob" in report
    assert "#9df22f" not in landing_css
    assert "dark ? '#0b1220' : '#f8fafc'" in theme_init

    for source in (channels, siteaudit, assets, competitors, questions, facts, blueprint):
        assert "ctx.role === 'viewer'" in source
        assert "plan.viewer_read_only" in source
    assert "totalMentions ?" in channels
    assert "avgScore == null" in siteaudit
    assert "fill_question_gap" in assets and "actionBlocked" in assets
    assert "common.owner_only" in team and "ctx.role !== 'owner'" in team
    assert "common.owner_only" in billing and "ctx.role !== 'owner'" in billing
    assert "common.owner_only" in engine_settings and "ctx.role !== 'owner'" in engine_settings
    assert "common.owner_only" in archive and "ctx.role !== 'owner'" in archive
    assert "common.owner_only" in outreach and "plan.viewer_read_only" in outreach
    assert "common.owner_only" in publishing and "plan.viewer_read_only" in publishing
    assert "common.owner_only" in project_settings and "plan.viewer_read_only" in project_settings
    assert "plan.viewer_read_only" in automation
    assert "plan.viewer_read_only" in entities
    assert "okSamples.length ?" in workbench and "common.unmeasured" in workbench

    assert 'aria-live="polite"' in auth_forgot and "form-status" in auth_forgot
    assert 'aria-live="polite"' in auth_reset and "auth.password_min_hint" in auth_reset
    assert "tError(err, 'auth.invalid_invite_desc')" in auth_invite
    assert "invitation_token: token" in auth_invite
    assert "7-Day" not in auth_register
    assert "auth.segment_label" in auth_register
    register_title = json.loads((root / "api/i18n/messages/en.json").read_text("utf-8"))["auth.register_title"]
    assert "14-Day" in register_title
    assert "projects.preflight" in onboarding and "projects.create" in onboarding and "no_sample" in onboarding
    assert "onboard-mode-option:has(input:checked)" in (root / "web/assets/styles/app.css").read_text("utf-8")
    assert "data-onboard-mode" in onboarding and 'name="ob-mode"' not in onboarding
    assert "data-influenced-question" in plan
    assert "share || 0" not in gaps and "common.unmeasured" in gaps
    assert "samplingModeBadge(item.sampling_mode)" in gaps
    assert "brandConfig.available" in branding_view and "brandConfig.can_edit" in branding_view
    assert "branding.delete()" in branding_view

    assert "this.role = me.role" in app_js and "role: state.role" in app_js
    assert (root / "web/assets/styles/app-print.css").is_file()
    assert "table-header-group" in (root / "web/assets/styles/app-print.css").read_text("utf-8")
    assert "@page" in (root / "web/sample-report.html").read_text("utf-8")


def test_public_trial_copy_matches_billing_ssot():
    from api.billing.plans import TRIAL_DAYS

    root = Path(__file__).resolve().parents[2]
    assert TRIAL_DAYS == 14
    assert f"{TRIAL_DAYS} days" in (root / "web/docs.html").read_text("utf-8")
    assert f"{TRIAL_DAYS}-day free trial" in (root / "web/terms.html").read_text("utf-8")
    assert f"Starter trial: {TRIAL_DAYS} days" in (root / "web/llms.txt").read_text("utf-8")
    assert "14-day trial" in (root / "web/index.html").read_text("utf-8")
    pricing = (root / "web/pricing.html").read_text("utf-8")
    assert "<th>Scheduled monitoring</th><td>—</td><td>Yes</td><td>Yes</td>" in pricing


def test_sample_evidence_drawer_and_pdf_export_use_real_contracts():
    root = Path(__file__).resolve().parents[2]
    drawer = (root / "web/app/components/evidence-drawer.js").read_text("utf-8")
    engines = (root / "web/app/views/engines.js").read_text("utf-8")
    api_js = (root / "web/app/api.js").read_text("utf-8")
    report = (root / "web/app/views/report.js").read_text("utf-8")

    assert "sample.run_id" in drawer
    assert "sample.question_id" in drawer
    assert "sample.raw_model" in drawer
    assert "sample.sampling_mode_code" in drawer
    assert "sample.search_enabled" in drawer
    assert "safeHttpUrl" in drawer
    assert "drawer: true" in drawer
    assert "data-evidence-index" in engines
    assert "openEvidenceDrawer(sample)" in engines
    assert "getDeliveryPdfUrl" in api_js
    assert "projects.getDeliveryPdfUrl" in report
