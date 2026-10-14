#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

ENV_FILE="${ENV_FILE:-.env.production}"
COMPOSE_FILE="docker-compose.prod.yml"
COMPOSE_EXTRA_FILE=""
export ENV_FILE

if [[ ! -f "$ENV_FILE" ]]; then
    printf 'Missing %s. Copy .env.production.example and fill every secret.\n' "$ENV_FILE" >&2
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    printf 'Python 3 is required for production preflight.\n' >&2
    exit 1
fi
python3 scripts/production_preflight.py --env-file "$ENV_FILE" --tls-mode external --migrate-legacy
if ! command -v docker >/dev/null 2>&1; then
    printf 'Docker is required.\n' >&2
    exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
    printf 'Docker Compose v2 is required.\n' >&2
    exit 1
fi

set -a
# shellcheck disable=SC1091
. "$ENV_FILE"
set +a

: "${DOMAIN:?DOMAIN is required in .env.production}"
: "${DATABASE_URL:?DATABASE_URL is required in .env.production}"
: "${JWT_SECRET:?JWT_SECRET is required in .env.production}"
: "${AES_KEY:?AES_KEY is required in .env.production}"
APP_PORT="${APP_PORT:-18000}"

database_host="$(DATABASE_URL="$DATABASE_URL" python3 -c 'from os import environ; from urllib.parse import urlparse; print(urlparse(environ["DATABASE_URL"]).hostname or "")')"
compose_profiles=()
if [[ "$database_host" == "postgres" ]]; then
    : "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required for local Compose PostgreSQL}"
    compose_profiles+=(--profile local-postgres)
    COMPOSE_EXTRA_FILE="docker-compose.prod.local-postgres.yml"
fi

compose() {
    local compose_files=(-f "$COMPOSE_FILE")
    if [[ -n "$COMPOSE_EXTRA_FILE" ]]; then
        compose_files+=(-f "$COMPOSE_EXTRA_FILE")
    fi
    docker compose "${compose_profiles[@]}" --env-file "$ENV_FILE" "${compose_files[@]}" "$@"
}

if [[ -z "${CITEAURA_SOURCE_REVISION:-}" || "${CITEAURA_SOURCE_REVISION:-}" == "unknown" ]]; then
    CITEAURA_SOURCE_REVISION="$(git rev-parse --short=12 HEAD 2>/dev/null || true)"
    CITEAURA_SOURCE_REVISION="${CITEAURA_SOURCE_REVISION:-unknown}"
fi
export CITEAURA_SOURCE_REVISION

compose config --quiet
compose up -d redis
if [[ "$database_host" == "postgres" ]]; then
    compose up -d --wait postgres
fi
compose build api worker beat
compose run --rm --user root api \
    chown -R citeaura:citeaura /app/work
compose run --rm api alembic upgrade head
# --force-recreate：compose 认为容器「已是期望状态」时只 start 不重建，于是已经坏掉的容器
# （例如端口未绑定）会跨部署一直存活，重新部署同样的代码永远修不好它。
compose up -d --force-recreate api worker beat

# CI 日志是长期可读的运维产物，容器日志可能夹带 DATABASE_URL 之类的连接串。
redact_secrets() {
    sed -E \
        -e 's#://[^:/@[:space:]]+:[^@/[:space:]]+@#://***:***@#g' \
        -e 's#([A-Za-z0-9_]*(PASSWORD|SECRET|TOKEN|API_KEY|AES_KEY|KEY))=[^[:space:]]+#\1=***#g'
}

# 宿主 SSH 常常不可达，就绪失败时必须在这里现场取证：只读、且只输出脱敏后的内容。
report_api_container() {
    local container
    container="$(compose ps -q api 2>/dev/null | head -n 1)"
    if [[ -z "$container" ]]; then
        printf '\nNo container is registered for the api service.\n' >&2
        return 0
    fi
    printf '\n--- api container ---\n' >&2
    docker inspect "$container" --format \
        'name={{.Name}} status={{.State.Status}} restarts={{.RestartCount}} image={{.Image}}' >&2 || true
    docker inspect "$container" --format \
        'health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' >&2 || true
    printf -- '--- api ports: an empty "published" means the host port was never bound ---\n' >&2
    docker inspect "$container" --format 'published={{json .NetworkSettings.Ports}}' >&2 || true
    docker inspect "$container" --format 'bindings={{json .HostConfig.PortBindings}}' >&2 || true
    docker inspect "$container" --format 'exposed={{json .Config.ExposedPorts}}' >&2 || true
    docker inspect "$container" --format 'networks={{json .NetworkSettings.Networks}}' >&2 || true
    docker inspect "$container" --format '{{json .State.Health}}' 2>/dev/null | redact_secrets >&2 || true
    printf -- '--- host listeners on port %s ---\n' "$APP_PORT" >&2
    { ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null || true; } \
        | grep -E -- ":${APP_PORT}([[:space:]]|$)" >&2 \
        || printf 'nothing is listening on port %s\n' "$APP_PORT" >&2
    printf -- '--- api logs (tail 80, secrets redacted) ---\n' >&2
    compose logs --tail=80 --no-color api 2>&1 | redact_secrets >&2 || true
}

for attempt in $(seq 1 30); do
    if curl --fail --silent --show-error \
        "http://127.0.0.1:${APP_PORT}/api/v1/health/ready" >/dev/null; then
        break
    fi
    if [[ "$attempt" -eq 30 ]]; then
        printf 'Deployment failed readiness check.\n' >&2
        curl --silent --show-error \
            "http://127.0.0.1:${APP_PORT}/api/v1/health/ready" >&2 || true
        printf '\n' >&2
        compose ps -a >&2
        report_api_container
        exit 1
    fi
    sleep 2
done

printf 'CiteAura application deployed on 127.0.0.1:%s. Caddy endpoint: https://%s\n' "$APP_PORT" "$DOMAIN"
