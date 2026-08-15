#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

ENV_FILE="${ENV_FILE:-.env.production}"
COMPOSE_FILE="docker-compose.prod.yml"
export ENV_FILE

if [[ ! -f "$ENV_FILE" ]]; then
    printf 'Missing %s. Copy .env.production.example and fill every secret.\n' "$ENV_FILE" >&2
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    printf 'Python 3 is required for production preflight.\n' >&2
    exit 1
fi
python3 scripts/production_preflight.py --env-file "$ENV_FILE" --tls-mode external
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

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config --quiet
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d redis
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" build api worker beat
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" run --rm --user root api \
    chown -R citeaura:citeaura /app/work
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" run --rm api alembic upgrade head
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d api worker beat

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
        docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps >&2
        exit 1
    fi
    sleep 2
done

printf 'CiteAura application deployed on 127.0.0.1:%s. Caddy endpoint: https://%s\n' "$APP_PORT" "$DOMAIN"
