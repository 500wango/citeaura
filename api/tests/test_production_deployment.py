import os
import re
import shlex
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_production_compose_binds_api_to_loopback_and_profiles_nginx():
    compose = (ROOT / "docker-compose.prod.yml").read_text("utf-8")
    local_compose = (ROOT / "docker-compose.yml").read_text("utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text("utf-8")

    assert "${ENV_FILE:-.env.production}" in compose
    assert '"127.0.0.1:${APP_PORT:-18000}:8000"' in compose
    assert 'FORWARDED_ALLOW_IPS:-127.0.0.1' in compose
    assert "--proxy-headers" in compose
    assert "--pool=prefork" in (ROOT / "Dockerfile").read_text("utf-8")
    assert "worker_pool=\"prefork\"" in (ROOT / "api/worker/celery_app.py").read_text("utf-8")
    assert "requirements.lock" in dockerfile
    assert "requirements.lock" in (ROOT / "docker-compose.yml").read_text("utf-8")
    assert 'profiles: ["standalone-nginx"]' in compose
    assert 'profiles: ["local-postgres"]' in compose
    assert "name: ${CITEAURA_WORK_VOLUME:-citeaura_citeaura_work}" in compose
    assert "external: ${CITEAURA_WORK_EXTERNAL:-false}" in compose
    assert "name: ${CITEAURA_WORK_VOLUME:-citeaura_citeaura_work}" in local_compose
    assert "external: ${CITEAURA_WORK_EXTERNAL:-false}" in local_compose
    for service in ("api", "worker", "beat"):
        section = local_compose.split(f"  {service}:\n", 1)[1]
        next_service = re.search(r"\n  [a-z][a-z0-9_-]*:\n", section)
        if next_service:
            section = section[: next_service.start()]
        assert "      - citeaura_work:/app/work" in section
    app = compose.split("x-app: &app\n", 1)[1].split("\nservices:\n", 1)[0]
    assert "    redis:\n      condition: service_healthy" in app
    local_override = (ROOT / "docker-compose.prod.local-postgres.yml").read_text("utf-8")
    assert "postgres:\n        condition: service_healthy" in local_override
    assert "image: postgres:${POSTGRES_MAJOR:-18}-alpine" in compose
    assert "postgres_data:/var/lib/postgresql" in compose
    assert '"5432' not in compose.split("  postgres:\n", 1)[1].split("  redis:\n", 1)[0]
    beat = compose.split("  beat:\n", 1)[1].split("\n  nginx:\n", 1)[0]
    assert "    command:" in beat
    assert "      command:" not in beat


def test_deploy_script_leaves_tls_to_host_caddy():
    deploy = (ROOT / "scripts/deploy.sh").read_text("utf-8")

    assert "--tls-mode external" in deploy
    assert "--migrate-legacy" in deploy
    assert 'APP_PORT="${APP_PORT:-18000}"' in deploy
    build = deploy.index("build api worker beat")
    repair_permissions = deploy.index("chown -R citeaura:citeaura /app/work")
    migrate = deploy.index("run --rm api alembic upgrade head")
    # 必须 force-recreate：否则「已是期望状态」的坏容器（端口未绑定）会跨部署存活，永远修不好
    start = deploy.index("up -d --force-recreate api worker beat")
    assert build < repair_permissions < migrate < start
    assert "run --rm --user root api" in deploy
    assert "up -d --build api worker beat nginx" not in deploy
    assert 'http://127.0.0.1:${APP_PORT}/api/v1/health/ready' in deploy
    assert 'curl --silent --show-error' in deploy
    assert 'database_host' in deploy
    assert 'compose up -d --wait postgres' in deploy
    assert '--profile local-postgres' in deploy


def test_beat_healthcheck_accepts_nul_separated_argv():
    """Docker 的 CMD 形式是 exec，/proc/1/cmdline 用 NUL 分隔 argv——找 ` beat`（空格 + beat）永远不成立，
    于是健康检查恒定失败，状态永远是 unhealthy，等于一个不发信号的死信号。"""
    compose = yaml.safe_load((ROOT / "docker-compose.prod.yml").read_text("utf-8"))
    command = compose["services"]["beat"]["healthcheck"]["test"][-1]

    # YAML 双引号标量会把 \0 解析成真正的 NUL 字节，反而弄坏 python 源码
    assert "\\" not in command
    assert "\x00" not in command
    assert "split(bytes([0]))" in command

    # 把 /proc/1/cmdline 换成合成文件，真的把这段代码跑起来
    prelude = (
        "import pathlib, os, tempfile\n"
        "_p = os.path.join(tempfile.mkdtemp(), 'cmdline')\n"
        "open(_p, 'wb').write(%r)\n"
        "_orig = pathlib.Path\n"
        "pathlib.Path = lambda *a, **k: _orig(_p) if a and a[0] == '/proc/1/cmdline' else _orig(*a, **k)\n"
    )

    def exit_code(argv):
        return subprocess.run(
            ["python3", "-c", prelude % argv + command], capture_output=True
        ).returncode

    assert exit_code(b"/usr/local/bin/python3.12\x00/usr/local/bin/celery\x00-A\x00"
                     b"api.worker.celery_app\x00beat\x00--loglevel=INFO\x00") == 0
    # 成员判断是整段 argv 精确比对，worker 的 cmdline 里不含独立的 beat
    assert exit_code(b"/usr/local/bin/python3.12\x00/usr/local/bin/celery\x00-A\x00"
                     b"api.worker.celery_app\x00worker\x00") == 1


def test_readiness_failure_collects_redacted_api_diagnostics():
    """宿主 SSH 常常不可达，就绪失败必须自己在 CI 日志里取证——否则只能靠猜。"""
    deploy = (ROOT / "scripts/deploy.sh").read_text("utf-8")

    assert "report_api_container" in deploy
    # 端口是否真的绑上，只有 inspect 说得清；ps 的 PORTS 为空就是同一个信号
    assert ".NetworkSettings.Ports" in deploy
    assert ".HostConfig.PortBindings" in deploy
    assert ".Config.ExposedPorts" in deploy
    assert ".NetworkSettings.Networks" in deploy
    assert ".State.Health" in deploy
    assert "ss -ltnp" in deploy
    assert "compose logs --tail=80 --no-color api" in deploy
    # 诊断必须在 exit 1 之前跑，否则永远看不到输出
    failure = deploy.split("Deployment failed readiness check.", 1)[1]
    assert failure.index("report_api_container") < failure.index("exit 1")

    # 只能输出脱敏后的内容：整份 compose config 会把 DATABASE_URL / JWT_SECRET 打进长期可读的日志
    assert "compose config >&2" not in deploy
    assert "compose config\n" not in deploy
    assert "redact_secrets" in deploy
    assert "://***:***@" in deploy
    assert "| redact_secrets >&2" in deploy


def test_deploy_diagnostics_redaction_scrubs_connection_strings_and_secret_assignments():
    """redact_secrets 是唯一挡住密钥进 CI 日志的地方，单独验证它的行为。"""
    deploy = (ROOT / "scripts/deploy.sh").read_text("utf-8")

    body = deploy.split("redact_secrets() {", 1)[1].split("\n}\n", 1)[0]
    expressions = re.findall(r"-e '([^']*)'", body)
    assert len(expressions) == 2, body

    samples = {
        "database_url": (
            "postgresql+psycopg://citeaura:s3cr3t@postgres:5432/citeaura",
            "postgresql+psycopg://***:***@postgres:5432/citeaura",
        ),
        "jwt": ("JWT_SECRET=abc123", "JWT_SECRET=***"),
        "aes": ("AES_KEY=deadbeef", "AES_KEY=***"),
        "provider": ("OPENCODE_API_KEY=oc_sk_live", "OPENCODE_API_KEY=***"),
        "postgres_password": ("POSTGRES_PASSWORD=hunter2", "POSTGRES_PASSWORD=***"),
    }
    # shlex.quote 而非 repr：repr 会把 sed 的 `\1` 反斜杠转义成 `\\1`，测试就不再验证真实脚本
    script = "\n".join(
        f"printf '%s\\n' {shlex.quote(value)} | sed -E "
        + " ".join(f"-e {shlex.quote(e)}" for e in expressions)
        for value, _ in samples.values()
    )
    result = subprocess.run(["bash", "-c", script], check=True, capture_output=True, text=True)
    scrubbed = result.stdout.splitlines()
    for (value, expected), line in zip(samples.values(), scrubbed):
        assert line == expected, f"{value!r} -> {line!r}"
        assert "s3cr3t" not in line and "hunter2" not in line and "abc123" not in line


def test_backup_verification_script_checks_freshness_permissions_and_restore_readability():
    script = ROOT / "scripts/verify-postgres-backup.sh"
    assert os.access(script, os.X_OK)
    text = script.read_text("utf-8")
    assert "MAX_AGE_HOURS" in text
    assert "stat -c '%a'" in text
    assert 'mode 600' in text
    assert "pg_restore --list" in text


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
    assert "--migrate-legacy" in text
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


def test_recovery_dispatch_inputs_default_to_inert():
    """恢复输入只在手动 dispatch 时生效，push 触发永远不重启 Docker。"""
    workflow = (ROOT / ".github/workflows/deploy-production.yml").read_text("utf-8")

    assert "repair_docker_networking:" in workflow
    assert "install_ssh_public_key:" in workflow
    # 两个输入都必须默认关闭/为空，否则 push 自动部署也会重启生产主机
    assert workflow.count("        default: false") == 1
    assert workflow.count('        default: ""') == 1
    assert "${{ inputs.repair_docker_networking || 'false' }}" in workflow
    assert "${{ inputs.install_ssh_public_key || '' }}" in workflow
    # 只有勾选后才会真的重启，且以 iptables 探针为准而非无条件重启
    assert "systemctl restart docker" in workflow
    assert '*"No chain/target/match"*)' in workflow
    assert "Docker iptables DOCKER chains are present; no restart needed." in workflow
    # filter 表只承载放行规则；发布端口的 DNAT 在 nat 表。只查 filter 会把 nat 缺失判成正常。
    assert "for table in filter nat; do" in workflow
    assert "iptables -t \"$table\" -S DOCKER" in workflow
    # 公钥经 base64 传递，避免远端 shell 重新分词
    assert "base64 -w0" in workflow
    assert "base64 -d" in workflow
    # 重启发生在动容器之前，否则修好也来不及
    assert workflow.index("systemctl restart docker") < workflow.index(
        "scripts/one-click-deploy.sh"
    )


def test_recovery_inputs_reject_unrecognised_public_keys():
    workflow = (ROOT / ".github/workflows/deploy-production.yml").read_text("utf-8")

    assert "ssh-ed25519\\ *|ssh-rsa\\ *|ecdsa-sha2-nistp256\\ *" in workflow
    assert "is not a recognised OpenSSH public key line" in workflow
    assert 'grep -qxF -- "$PUBLIC_KEY" "$AUTHORIZED_KEYS"' in workflow
