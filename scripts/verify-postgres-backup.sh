#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/citeaura/daily}"
MAX_AGE_HOURS="${MAX_AGE_HOURS:-26}"

case "$MAX_AGE_HOURS" in
  ''|*[!0-9]*)
    echo "MAX_AGE_HOURS must be a non-negative integer" >&2
    exit 2
    ;;
esac

latest="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name '*.dump' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 1 | cut -d' ' -f2-)"
if [ -z "$latest" ]; then
  echo "No PostgreSQL dump found in $BACKUP_DIR" >&2
  exit 1
fi

now="$(date +%s)"
mtime="$(stat -c '%Y' -- "$latest")"
age=$((now - mtime))
max_age=$((MAX_AGE_HOURS * 3600))
if [ "$age" -gt "$max_age" ]; then
  echo "Latest PostgreSQL dump is too old: $latest (${age}s; limit ${max_age}s)" >&2
  exit 1
fi

mode="$(stat -c '%a' -- "$latest")"
if [ "$mode" != "600" ]; then
  echo "PostgreSQL dump must have mode 600: $latest (found $mode)" >&2
  exit 1
fi

pg_restore --list "$latest" >/dev/null

# 可选恢复演练：仅允许恢复到名字含 restore/verify 的临时库，防止误清生产库。
if [ "${RESTORE_CHECK:-0}" = "1" ]; then
  restore_url="${RESTORE_DATABASE_URL:-}"
  if [ -z "$restore_url" ]; then
    echo "RESTORE_DATABASE_URL is required when RESTORE_CHECK=1" >&2
    exit 2
  fi
  case "$restore_url" in
    *restore*|*verify*) ;;
    *)
      echo "RESTORE_DATABASE_URL must target a restore/verify database" >&2
      exit 2
      ;;
  esac
  pg_restore --exit-on-error --clean --if-exists --no-owner --no-privileges \
    --dbname="$restore_url" "$latest" >/dev/null
fi

printf 'PostgreSQL backup OK: %s (age %ss)\n' "$latest" "$age"
