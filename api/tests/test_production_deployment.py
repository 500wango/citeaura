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

    assert "--skip-certificate" in deploy
    assert 'APP_PORT="${APP_PORT:-18000}"' in deploy
    build = deploy.index("build api worker beat")
    migrate = deploy.index("run --rm api alembic upgrade head")
    start = deploy.index("up -d api worker beat")
    assert build < migrate < start
    assert "up -d --build api worker beat nginx" not in deploy
    assert 'http://127.0.0.1:${APP_PORT}/api/v1/health/ready' in deploy


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
    assert "api worker beat nginx" not in text
