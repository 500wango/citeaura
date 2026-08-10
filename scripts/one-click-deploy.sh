#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

ENV_FILE="${ENV_FILE:-.env.production}"
CADDYFILE="${CADDYFILE:-/etc/caddy/Caddyfile}"
CADDY_SITE_DIR="${CADDY_SITE_DIR:-/etc/caddy/sites}"
SKIP_PUBLIC_CHECK=false

usage() {
    cat <<'EOF'
Usage: scripts/one-click-deploy.sh [options]

Deploy CiteAura with Docker Compose and configure the host Caddy instance.

Options:
  --env-file PATH    Production environment file (default: .env.production)
  --caddyfile PATH   Host Caddyfile (default: /etc/caddy/Caddyfile)
  --site-dir PATH    Managed Caddy site directory (default: /etc/caddy/sites)
  --skip-public-check
                     Do not wait for the public HTTPS endpoint
  -h, --help         Show this help

The environment file must contain the real DOMAIN, APP_PORT, database,
JWT and AES settings required by production_preflight.py. Stripe and auth
SMTP settings are required only when their feature switches are enabled.
EOF
}

while (($#)); do
    case "$1" in
        --env-file)
            [[ $# -ge 2 ]] || { printf '%s\n' '--env-file requires a path' >&2; exit 2; }
            ENV_FILE="$2"
            shift 2
            ;;
        --caddyfile)
            [[ $# -ge 2 ]] || { printf '%s\n' '--caddyfile requires a path' >&2; exit 2; }
            CADDYFILE="$2"
            shift 2
            ;;
        --site-dir)
            [[ $# -ge 2 ]] || { printf '%s\n' '--site-dir requires a path' >&2; exit 2; }
            CADDY_SITE_DIR="$2"
            shift 2
            ;;
        --skip-public-check)
            SKIP_PUBLIC_CHECK=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf 'Unknown option: %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

case "$ENV_FILE" in
    /*) ;;
    *) ENV_FILE="$PROJECT_DIR/$ENV_FILE" ;;
esac
export ENV_FILE

if [[ ! -f "$ENV_FILE" ]]; then
    printf 'Missing %s. Create it from .env.production.example and fill the production credentials.\n' "$ENV_FILE" >&2
    exit 1
fi
if [[ ! -f "$CADDYFILE" ]]; then
    printf 'Caddyfile not found: %s\n' "$CADDYFILE" >&2
    exit 1
fi
for command in python3 docker curl caddy mktemp install grep cp tee; do
    if ! command -v "$command" >/dev/null 2>&1; then
        printf 'Required command not found: %s\n' "$command" >&2
        exit 1
    fi
done
if ! docker compose version >/dev/null 2>&1; then
    printf 'Docker Compose v2 is required.\n' >&2
    exit 1
fi

python3 scripts/production_preflight.py --env-file "$ENV_FILE" --skip-certificate

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

: "${DOMAIN:?DOMAIN is required in the production environment file}"
APP_PORT="${APP_PORT:-18000}"
if ! [[ "$APP_PORT" =~ ^[0-9]+$ ]] || ((APP_PORT < 1024 || APP_PORT > 65535)); then
    printf 'APP_PORT must be an integer between 1024 and 65535.\n' >&2
    exit 1
fi

CADDY_BIN="$(command -v caddy)"
if ((EUID == 0)); then
    SUDO=()
else
    if ! command -v sudo >/dev/null 2>&1; then
        printf 'sudo is required to update the host Caddy configuration.\n' >&2
        exit 1
    fi
    SUDO=(sudo)
fi

printf 'Deploying CiteAura containers on 127.0.0.1:%s...\n' "$APP_PORT"
ENV_FILE="$ENV_FILE" "$SCRIPT_DIR/deploy.sh"

printf 'Configuring Caddy for %s...\n' "$DOMAIN"
if ((${#SUDO[@]})); then
    "${SUDO[@]}" -v
fi

BACKUP_DIR="$(mktemp -d)"
SITE_FILE="$CADDY_SITE_DIR/citeaura.caddy"
CADDYFILE_BACKUP="$BACKUP_DIR/Caddyfile"
SITE_BACKUP="$BACKUP_DIR/citeaura.caddy"
SITE_CANDIDATE="$BACKUP_DIR/citeaura.candidate.caddy"
SITE_EXISTED=false
CADDY_CHANGED=false

cleanup() {
    if [[ -n "${BACKUP_DIR:-}" && -d "$BACKUP_DIR" ]]; then
        rm -rf -- "$BACKUP_DIR"
    fi
}

reload_caddy() {
    if command -v systemctl >/dev/null 2>&1 && "${SUDO[@]}" systemctl is-active --quiet caddy; then
        "${SUDO[@]}" systemctl reload caddy
    else
        "${SUDO[@]}" "$CADDY_BIN" reload --config "$CADDYFILE"
    fi
}

restore_caddy() {
    local exit_code=$?
    if (($#)); then
        exit_code="$1"
    fi
    trap - ERR
    trap - INT
    trap - TERM
    set +e
    if [[ "$CADDY_CHANGED" == true ]]; then
        printf 'Caddy update failed; restoring the previous configuration.\n' >&2
        "${SUDO[@]}" cp -- "$CADDYFILE_BACKUP" "$CADDYFILE"
        if [[ "$SITE_EXISTED" == true ]]; then
            "${SUDO[@]}" cp -- "$SITE_BACKUP" "$SITE_FILE"
        else
            "${SUDO[@]}" rm -f -- "$SITE_FILE"
        fi
        "${SUDO[@]}" "$CADDY_BIN" validate --config "$CADDYFILE" >/dev/null 2>&1
        reload_caddy >/dev/null 2>&1
    fi
    exit "$exit_code"
}

trap cleanup EXIT
trap restore_caddy ERR
trap 'restore_caddy 130' INT
trap 'restore_caddy 143' TERM

"${SUDO[@]}" cp -- "$CADDYFILE" "$CADDYFILE_BACKUP"
if "${SUDO[@]}" test -f "$SITE_FILE"; then
    SITE_EXISTED=true
    "${SUDO[@]}" cp -- "$SITE_FILE" "$SITE_BACKUP"
fi

{
    printf '%s {\n' "$DOMAIN"
    printf '    encode zstd gzip\n'
    printf '    reverse_proxy 127.0.0.1:%s\n' "$APP_PORT"
    printf '}\n'
} >"$SITE_CANDIDATE"

"${SUDO[@]}" install -d -m 0755 -- "$CADDY_SITE_DIR"
"${SUDO[@]}" install -m 0644 -- "$SITE_CANDIDATE" "$SITE_FILE"
CADDY_CHANGED=true

IMPORT_LINE="import $CADDY_SITE_DIR/*.caddy"
if ! "${SUDO[@]}" grep -Fqx -- "$IMPORT_LINE" "$CADDYFILE"; then
    printf '\n%s\n' "$IMPORT_LINE" | "${SUDO[@]}" tee -a "$CADDYFILE" >/dev/null
fi

"${SUDO[@]}" "$CADDY_BIN" validate --config "$CADDYFILE"
reload_caddy
CADDY_CHANGED=false

if [[ "$SKIP_PUBLIC_CHECK" == false ]]; then
    PUBLIC_READY=false
    for _attempt in $(seq 1 18); do
        if curl --fail --silent --show-error "https://${DOMAIN}/api/v1/health/ready" >/dev/null 2>&1; then
            PUBLIC_READY=true
            break
        fi
        sleep 5
    done
    if [[ "$PUBLIC_READY" == false ]]; then
        printf 'WARN: local deployment is healthy, but https://%s is not ready yet. Check DNS and Caddy logs.\n' "$DOMAIN" >&2
    fi
fi

printf '\nCiteAura deployment completed.\n'
printf 'Application: https://%s\n' "$DOMAIN"
printf 'Local upstream: http://127.0.0.1:%s\n' "$APP_PORT"
printf 'Caddy site: %s\n' "$SITE_FILE"
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml ps
