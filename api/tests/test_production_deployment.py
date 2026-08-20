import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_production_compose_binds_api_to_loopback_and_profiles_nginx():
    compose = (ROOT / "docker-compose.prod.yml").read_text("utf-8")

    assert "${ENV_FILE:-.env.production}" in compose
    assert '"127.0.0.1:${APP_PORT:-18000}:8000"' in compose
    assert 'profiles: ["standalone-nginx"]' in compose
    beat = compose.split("  beat:\n", 1)[1].split("\n  nginx:\n", 1)[0]
    assert "    command:" in beat
    assert "      command:" not in beat


def test_deploy_script_leaves_tls_to_host_caddy():
    deploy = (ROOT / "scripts/deploy.sh").read_text("utf-8")

    assert "--tls-mode external" in deploy
    assert 'APP_PORT="${APP_PORT:-18000}"' in deploy
    build = deploy.index("build api worker beat")
    repair_permissions = deploy.index("chown -R citeaura:citeaura /app/work")
    migrate = deploy.index("run --rm api alembic upgrade head")
    start = deploy.index("up -d api worker beat")
    assert build < repair_permissions < migrate < start
    assert "run --rm --user root api" in deploy
    assert "up -d --build api worker beat nginx" not in deploy
    assert 'http://127.0.0.1:${APP_PORT}/api/v1/health/ready' in deploy
    assert 'curl --silent --show-error' in deploy


def test_long_revision_expands_alembic_version_before_schema_changes():
    migration = (ROOT / "api/migrations/versions/0011_session_and_project_lifecycle.py").read_text("utf-8")

    resize = migration.index('"alembic_version"')
    schema_change = migration.index('op.add_column("users"')
    assert resize < schema_change
    assert "type_=sa.String(length=128)" in migration


def test_one_click_deploy_is_executable_and_documents_safe_caddy_update():
    script = ROOT / "scripts/one-click-deploy.sh"
    text = script.read_text("utf-8")

    assert os.access(script, os.X_OK)
    result = subprocess.run([str(script), "--help"], check=True, capture_output=True, text=True)
    assert "configure the host Caddy" in result.stdout
    assert 'ENV_FILE="$ENV_FILE" "$SCRIPT_DIR/deploy.sh"' in text
    assert "citeaura.candidate.caddy" in text
    assert "validate --config" in text
    assert "restoring the previous configuration" in text
    assert "restore_caddy 130" in text
    assert "restore_caddy 143" in text
    assert "www.%s {\\n" in text
    assert "redir https://%s{uri} permanent" in text
    assert '"https://www.${DOMAIN}/sitemap.xml"' in text
    assert '"https://${DOMAIN}/sitemap.xml"' in text
    assert "api worker beat nginx" not in text


def test_github_main_push_deploys_with_strict_ssh_host_verification():
    workflow = (ROOT / ".github/workflows/deploy-production.yml").read_text("utf-8")

    assert "push:\n    branches:\n      - main" in workflow
    assert "workflow_dispatch:" in workflow
    assert "environment:\n      name: production" in workflow
    assert "group: citeaura-production" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "BatchMode=yes" in workflow
    assert "IdentitiesOnly=yes" in workflow
    assert "StrictHostKeyChecking=yes" in workflow
    assert "UserKnownHostsFile=$KNOWN_HOSTS_FILE" in workflow
    assert "PROJECT_DIR=/opt/citeaura" in workflow
    assert "git pull --ff-only origin main" in workflow
    assert "git merge-base --is-ancestor" in workflow
    assert "scripts/one-click-deploy.sh" in workflow
    assert "needs: test" in workflow
    assert "make test" in workflow
    assert "--env-file \"$PROJECT_DIR/.env.production\"" in workflow
    assert "DATABASE_URL" not in workflow
    assert "JWT_SECRET" not in workflow
    assert "scp " not in workflow
