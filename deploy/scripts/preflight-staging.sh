#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
DEPLOY_ENV=${1:-"$ROOT_DIR/deploy/.env.staging"}

fail() {
  printf 'staging preflight error: %s\n' "$*" >&2
  exit 2
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"
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

require_immutable_image() {
  name=$1
  value=$2
  printf '%s' "$value" | grep -Eq '@sha256:[0-9a-f]{64}$' || \
    fail "$name must use an immutable @sha256 digest"
}

[ -f "$DEPLOY_ENV" ] || fail "deployment env not found: $DEPLOY_ENV"
require_command docker
require_command grep
require_command stat
require_private_file DEPLOY_ENV "$DEPLOY_ENV"

set -a
# shellcheck disable=SC1090
. "$DEPLOY_ENV"
set +a

[ "${DEPLOY_ENVIRONMENT:-}" = "staging" ] || fail "DEPLOY_ENVIRONMENT must be exactly staging"
: "${ORAL_SERVER_IMAGE:?ORAL_SERVER_IMAGE is required}"
: "${ORAL_WEB_IMAGE:?ORAL_WEB_IMAGE is required}"
: "${ORAL_ADMIN_IMAGE:?ORAL_ADMIN_IMAGE is required}"
: "${ORAL_GATEWAY_IMAGE:?ORAL_GATEWAY_IMAGE is required}"
: "${ORAL_ENV_FILE:?ORAL_ENV_FILE is required}"
: "${STAGING_EXPECTED_COS_BUCKET:?STAGING_EXPECTED_COS_BUCKET is required}"
: "${STAGING_EXPECTED_DATABASE_HOST:?STAGING_EXPECTED_DATABASE_HOST is required}"
: "${STAGING_EXPECTED_REDIS_HOST:?STAGING_EXPECTED_REDIS_HOST is required}"
: "${STAGING_EXPECTED_MEDIA_HOST:?STAGING_EXPECTED_MEDIA_HOST is required}"

require_immutable_image ORAL_SERVER_IMAGE "$ORAL_SERVER_IMAGE"
require_immutable_image ORAL_WEB_IMAGE "$ORAL_WEB_IMAGE"
require_immutable_image ORAL_ADMIN_IMAGE "$ORAL_ADMIN_IMAGE"
require_immutable_image ORAL_GATEWAY_IMAGE "$ORAL_GATEWAY_IMAGE"
require_private_file ORAL_ENV_FILE "$ORAL_ENV_FILE"

docker pull "$ORAL_SERVER_IMAGE" >/dev/null

set -- docker run --rm
if [ -n "${STAGING_DOCKER_NETWORK:-}" ]; then
  set -- "$@" --network "$STAGING_DOCKER_NETWORK"
fi
set -- "$@" \
  --env-file "$ORAL_ENV_FILE" \
  "$ORAL_SERVER_IMAGE" \
  python -m scripts.staging_preflight \
  --expected-bucket "$STAGING_EXPECTED_COS_BUCKET" \
  --expected-database-host "$STAGING_EXPECTED_DATABASE_HOST" \
  --expected-redis-host "$STAGING_EXPECTED_REDIS_HOST" \
  --expected-media-host "$STAGING_EXPECTED_MEDIA_HOST"

case "${STAGING_ALLOW_VERIFIED_PUBLISH:-false}" in
  true) set -- "$@" --allow-verified-publish ;;
  false) ;;
  *) fail "STAGING_ALLOW_VERIFIED_PUBLISH must be true or false" ;;
esac

printf '%s\n' 'running Staging runtime preflight inside the immutable Server image...'
"$@"
