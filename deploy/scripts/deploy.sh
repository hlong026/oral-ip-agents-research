#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
DEPLOY_ENV=${1:-"$ROOT_DIR/deploy/.env.prod"}
COMPOSE_FILE="$ROOT_DIR/docker-compose.prod.yml"

fail() {
  printf 'deploy error: %s\n' "$*" >&2
  exit 2
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"
}

require_immutable_image() {
  name=$1
  value=$2
  printf '%s' "$value" | grep -Eq '@sha256:[0-9a-f]{64}$' || \
    fail "$name must use an immutable @sha256 digest"
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
require_command docker
require_command curl
require_command python3
require_command grep
require_command stat

set -a
# shellcheck disable=SC1090
. "$DEPLOY_ENV"
set +a

: "${ORAL_SERVER_IMAGE:?ORAL_SERVER_IMAGE is required}"
: "${ORAL_WEB_IMAGE:?ORAL_WEB_IMAGE is required}"
: "${ORAL_ADMIN_IMAGE:?ORAL_ADMIN_IMAGE is required}"
: "${ORAL_GATEWAY_IMAGE:?ORAL_GATEWAY_IMAGE is required}"
: "${ORAL_ENV_FILE:?ORAL_ENV_FILE is required}"
: "${DEPLOY_READY_URL:?DEPLOY_READY_URL is required}"

require_immutable_image ORAL_SERVER_IMAGE "$ORAL_SERVER_IMAGE"
require_immutable_image ORAL_WEB_IMAGE "$ORAL_WEB_IMAGE"
require_immutable_image ORAL_ADMIN_IMAGE "$ORAL_ADMIN_IMAGE"
require_immutable_image ORAL_GATEWAY_IMAGE "$ORAL_GATEWAY_IMAGE"
require_private_file ORAL_ENV_FILE "$ORAL_ENV_FILE"

compose() {
  docker compose --env-file "$DEPLOY_ENV" -f "$COMPOSE_FILE" "$@"
}

printf '%s\n' '1/6 validating production compose...'
compose config --quiet

printf '%s\n' '2/6 pulling immutable images...'
compose pull server worker web admin gateway

printf '%s\n' '3/6 stopping old API and Worker before schema migration...'
compose stop worker server || true

printf '%s\n' '4/6 running database migration with the release server image...'
compose --profile migration run --rm --no-deps migration

printf '%s\n' '5/6 starting application services...'
compose up -d --remove-orphans server worker web admin gateway

printf '%s\n' '6/6 waiting for /readyz...'
attempt=0
while :; do
  attempt=$((attempt + 1))
  if payload=$(curl --fail --silent --show-error --max-time 10 "$DEPLOY_READY_URL" 2>/dev/null); then
    if printf '%s' "$payload" | python3 -c '
import json, sys
payload = json.load(sys.stdin)
assert payload.get("ok") is True, payload
assert payload.get("env") == "prod", payload
storage = payload.get("dependencies", {}).get("storage", {})
assert storage.get("ok") is True, storage
assert storage.get("driver") == "s3", storage
'; then
      printf '%s\n' 'deployment ready'
      compose ps
      exit 0
    fi
  fi
  [ "$attempt" -lt "${DEPLOY_READY_ATTEMPTS:-30}" ] || fail "readyz did not become healthy"
  sleep "${DEPLOY_READY_INTERVAL_SECONDS:-5}"
done
