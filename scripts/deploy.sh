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
fi

compose() {
    docker compose "${compose_profiles[@]}" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
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
compose up -d api worker beat

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
        compose ps >&2
        exit 1
    fi
    sleep 2
done

printf 'CiteAura application deployed on 127.0.0.1:%s. Caddy endpoint: https://%s\n' "$APP_PORT" "$DOMAIN"
