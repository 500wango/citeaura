#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

ENV_FILE=".env.production"
COMPOSE_FILE="docker-compose.prod.yml"

if [[ ! -f "$ENV_FILE" ]]; then
    printf 'Missing %s. Copy .env.production.example and fill every secret.\n' "$ENV_FILE" >&2
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    printf 'Python 3 is required for production preflight.\n' >&2
    exit 1
fi
python3 scripts/production_preflight.py --env-file "$ENV_FILE"
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
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required in .env.production}"
: "${JWT_SECRET:?JWT_SECRET is required in .env.production}"
: "${AES_KEY:?AES_KEY is required in .env.production}"

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config --quiet
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d postgres redis
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" run --rm api alembic upgrade head
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --build api worker beat nginx

for attempt in $(seq 1 30); do
    if curl --fail --silent --show-error \
        --resolve "${DOMAIN}:443:127.0.0.1" \
        "https://${DOMAIN}/api/v1/health/ready" >/dev/null; then
        break
    fi
    if [[ "$attempt" -eq 30 ]]; then
        printf 'Deployment failed readiness check.\n' >&2
        docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps >&2
        exit 1
    fi
    sleep 2
done

printf 'DisvorAI deployed. HTTPS endpoint: https://%s\n' "$DOMAIN"
