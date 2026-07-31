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

mkdir -p deploy/certs
if [[ ! -s deploy/certs/fullchain.pem || ! -s deploy/certs/privkey.pem ]]; then
    printf 'No TLS certificate found; generating a temporary self-signed certificate for %s.\n' "$DOMAIN" >&2
    openssl req -x509 -nodes -newkey rsa:2048 -days 30 \
        -keyout deploy/certs/privkey.pem \
        -out deploy/certs/fullchain.pem \
        -subj "/CN=${DOMAIN}" \
        -addext "subjectAltName=DNS:${DOMAIN}"
    chmod 600 deploy/certs/privkey.pem
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d postgres redis
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" run --rm api alembic upgrade head
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --build api worker beat nginx

printf 'DisvorAI deployed. HTTPS endpoint: https://%s\n' "$DOMAIN"
