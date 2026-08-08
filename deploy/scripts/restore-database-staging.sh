#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
DEPLOY_ENV=${1:-"$ROOT_DIR/deploy/.env.staging"}
METADATA_FILE=${2:-}
CONFIRM=${3:-}
COMPOSE_FILE="$ROOT_DIR/docker-compose.prod.yml"

fail() {
  printf 'staging restore error: %s\n' "$*" >&2
  exit 2
}

require_private_file() {
  name=$1
  path=$2
  [ -f "$path" ] || fail "$name not found: $path"
  mode=$(stat -c '%a' "$path")
  case "$mode" in
    400|600) ;;
    *) fail "$name must have owner-only permissions (0400 or 0600), got $mode" ;;
  esac
}

[ -f "$DEPLOY_ENV" ] || fail "deployment env not found: $DEPLOY_ENV"
[ -n "$METADATA_FILE" ] || fail "usage: restore-database-staging.sh <deploy-env> <backup-metadata.json> RESTORE_STAGING_ONLY"
[ "$CONFIRM" = "RESTORE_STAGING_ONLY" ] || fail "explicit RESTORE_STAGING_ONLY confirmation is required"
command -v docker >/dev/null 2>&1 || fail "missing command: docker"
command -v python3 >/dev/null 2>&1 || fail "missing command: python3"
command -v stat >/dev/null 2>&1 || fail "missing command: stat"
require_private_file DEPLOY_ENV "$DEPLOY_ENV"
require_private_file BACKUP_METADATA "$METADATA_FILE"

set -a
# shellcheck disable=SC1090
. "$DEPLOY_ENV"
set +a

[ "${DEPLOY_ENVIRONMENT:-}" = "staging" ] || fail "restore is allowed only for DEPLOY_ENVIRONMENT=staging"
: "${ORAL_SERVER_IMAGE:?ORAL_SERVER_IMAGE is required}"
: "${ORAL_ENV_FILE:?ORAL_ENV_FILE is required}"
: "${STAGING_EXPECTED_DATABASE_HOST:?STAGING_EXPECTED_DATABASE_HOST is required}"
: "${STAGING_EXPECTED_DATABASE_NAME:?STAGING_EXPECTED_DATABASE_NAME is required}"
: "${DEPLOY_READY_URL:?DEPLOY_READY_URL is required}"
require_private_file ORAL_ENV_FILE "$ORAL_ENV_FILE"

metadata_dir=$(CDPATH= cd -- "$(dirname -- "$METADATA_FILE")" && pwd)
metadata_name=$(basename -- "$METADATA_FILE")
dump_name=$(python3 -c '
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)
name = payload.get("dumpFile")
assert isinstance(name, str) and name and "/" not in name and "\\" not in name, payload
print(name)
' "$METADATA_FILE")
dump_file="$metadata_dir/$dump_name"
require_private_file BACKUP_DUMP "$dump_file"

compose() {
  docker compose --env-file "$DEPLOY_ENV" -f "$COMPOSE_FILE" "$@"
}

printf '%s\n' '1/5 stopping Staging API and Worker before destructive restore...'
compose stop worker server || true

printf '%s\n' '2/5 restoring verified Staging backup...'
set -- docker run --rm
if [ -n "${STAGING_DOCKER_NETWORK:-}" ]; then
  set -- "$@" --network "$STAGING_DOCKER_NETWORK"
fi
set -- "$@" \
  --env-file "$ORAL_ENV_FILE" \
  --volume "$metadata_dir:/backup:ro" \
  "$ORAL_SERVER_IMAGE" \
  python -m scripts.database_restore_staging \
  --dump "/backup/$dump_name" \
  --metadata "/backup/$metadata_name" \
  --expected-database-host "$STAGING_EXPECTED_DATABASE_HOST" \
  --expected-database-name "$STAGING_EXPECTED_DATABASE_NAME" \
  --confirm RESTORE_STAGING_ONLY
"$@"

printf '%s\n' '3/5 upgrading restored schema to the checked-out release head...'
compose --profile migration run --rm --no-deps migration

printf '%s\n' '4/5 restarting Staging API and Worker...'
compose up -d server worker

printf '%s\n' '5/5 validating restored environment through the authenticated Smoke gate...'
"$ROOT_DIR/deploy/scripts/staging-smoke.sh" "$DEPLOY_ENV"
printf '%s\n' 'Staging database restore drill passed'
