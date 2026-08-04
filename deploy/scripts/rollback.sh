#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
DEPLOY_ENV=${1:-"$ROOT_DIR/deploy/.env.prod"}
COMPOSE_FILE="$ROOT_DIR/docker-compose.prod.yml"

fail() {
  printf 'rollback error: %s\n' "$*" >&2
  exit 2
}

require_immutable_image() {
  name=$1
  value=$2
  printf '%s' "$value" | grep -Eq '@sha256:[0-9a-f]{64}$' || \
    fail "$name must use an immutable @sha256 digest"
}

[ -f "$DEPLOY_ENV" ] || fail "deployment env not found: $DEPLOY_ENV"
command -v docker >/dev/null 2>&1 || fail "missing command: docker"
command -v curl >/dev/null 2>&1 || fail "missing command: curl"
command -v python3 >/dev/null 2>&1 || fail "missing command: python3"
command -v grep >/dev/null 2>&1 || fail "missing command: grep"

set -a
# shellcheck disable=SC1090
. "$DEPLOY_ENV"
set +a

: "${PREVIOUS_ORAL_SERVER_IMAGE:?PREVIOUS_ORAL_SERVER_IMAGE is required}"
: "${PREVIOUS_ORAL_WEB_IMAGE:?PREVIOUS_ORAL_WEB_IMAGE is required}"
: "${PREVIOUS_ORAL_ADMIN_IMAGE:?PREVIOUS_ORAL_ADMIN_IMAGE is required}"
: "${PREVIOUS_ORAL_GATEWAY_IMAGE:?PREVIOUS_ORAL_GATEWAY_IMAGE is required}"
: "${DEPLOY_READY_URL:?DEPLOY_READY_URL is required}"

require_immutable_image PREVIOUS_ORAL_SERVER_IMAGE "$PREVIOUS_ORAL_SERVER_IMAGE"
require_immutable_image PREVIOUS_ORAL_WEB_IMAGE "$PREVIOUS_ORAL_WEB_IMAGE"
require_immutable_image PREVIOUS_ORAL_ADMIN_IMAGE "$PREVIOUS_ORAL_ADMIN_IMAGE"
require_immutable_image PREVIOUS_ORAL_GATEWAY_IMAGE "$PREVIOUS_ORAL_GATEWAY_IMAGE"

export ORAL_SERVER_IMAGE=$PREVIOUS_ORAL_SERVER_IMAGE
export ORAL_WEB_IMAGE=$PREVIOUS_ORAL_WEB_IMAGE
export ORAL_ADMIN_IMAGE=$PREVIOUS_ORAL_ADMIN_IMAGE
export ORAL_GATEWAY_IMAGE=$PREVIOUS_ORAL_GATEWAY_IMAGE

compose() {
  docker compose --env-file "$DEPLOY_ENV" -f "$COMPOSE_FILE" "$@"
}

printf '%s\n' 'Rollback does not run an automatic database downgrade.'
printf '%s\n' 'Confirm the previous image is compatible with the current schema before continuing.'
[ "${ROLLBACK_SCHEMA_COMPATIBLE:-false}" = "true" ] || fail "set ROLLBACK_SCHEMA_COMPATIBLE=true after schema review"

compose config --quiet
compose pull server worker web admin gateway
compose stop worker server gateway || true
compose up -d --remove-orphans server worker web admin gateway

attempt=0
while :; do
  attempt=$((attempt + 1))
  if payload=$(curl --fail --silent --show-error --max-time 10 "$DEPLOY_READY_URL" 2>/dev/null); then
    if printf '%s' "$payload" | python3 -c '
import json, sys
payload = json.load(sys.stdin)
assert payload.get("ok") is True, payload
assert payload.get("env") == "prod", payload
'; then
      printf '%s\n' 'rollback ready'
      compose ps
      exit 0
    fi
  fi
  [ "$attempt" -lt "${DEPLOY_READY_ATTEMPTS:-30}" ] || fail "rollback readyz did not become healthy"
  sleep "${DEPLOY_READY_INTERVAL_SECONDS:-5}"
done
