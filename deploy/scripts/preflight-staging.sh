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

require_positive_integer() {
  name=$1
  value=$2
  printf '%s' "$value" | grep -Eq '^[1-9][0-9]*$' || fail "$name must be a positive integer"
}

[ -f "$DEPLOY_ENV" ] || fail "deployment env not found: $DEPLOY_ENV"
require_command awk
require_command df
require_command docker
require_command getent
require_command grep
require_command python3
require_command stat
require_private_file DEPLOY_ENV "$DEPLOY_ENV"

docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is required"

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
: "${WEB_HOST:?WEB_HOST is required}"
: "${ADMIN_HOST:?ADMIN_HOST is required}"
: "${DEPLOY_READY_URL:?DEPLOY_READY_URL is required}"
: "${STAGING_EXPECTED_COS_BUCKET:?STAGING_EXPECTED_COS_BUCKET is required}"
: "${STAGING_EXPECTED_DATABASE_HOST:?STAGING_EXPECTED_DATABASE_HOST is required}"
: "${STAGING_EXPECTED_REDIS_HOST:?STAGING_EXPECTED_REDIS_HOST is required}"
: "${STAGING_EXPECTED_MEDIA_HOST:?STAGING_EXPECTED_MEDIA_HOST is required}"

STAGING_MIN_FREE_DISK_MB=${STAGING_MIN_FREE_DISK_MB:-10240}
STAGING_MIN_AVAILABLE_MEMORY_MB=${STAGING_MIN_AVAILABLE_MEMORY_MB:-2048}
STAGING_MIN_FREE_INODES=${STAGING_MIN_FREE_INODES:-10000}
require_positive_integer STAGING_MIN_FREE_DISK_MB "$STAGING_MIN_FREE_DISK_MB"
require_positive_integer STAGING_MIN_AVAILABLE_MEMORY_MB "$STAGING_MIN_AVAILABLE_MEMORY_MB"
require_positive_integer STAGING_MIN_FREE_INODES "$STAGING_MIN_FREE_INODES"

require_immutable_image ORAL_SERVER_IMAGE "$ORAL_SERVER_IMAGE"
require_immutable_image ORAL_WEB_IMAGE "$ORAL_WEB_IMAGE"
require_immutable_image ORAL_ADMIN_IMAGE "$ORAL_ADMIN_IMAGE"
require_immutable_image ORAL_GATEWAY_IMAGE "$ORAL_GATEWAY_IMAGE"
require_private_file ORAL_ENV_FILE "$ORAL_ENV_FILE"

available_memory_mb=$(awk '/MemAvailable:/ {print int($2 / 1024); found=1} END {if (!found) exit 1}' /proc/meminfo) || \
  fail "unable to read available memory"
free_disk_mb=$(df -Pm "$ROOT_DIR" | awk 'NR==2 {print $4}')
free_inodes=$(df -Pi "$ROOT_DIR" | awk 'NR==2 {print $4}')

[ "$available_memory_mb" -ge "$STAGING_MIN_AVAILABLE_MEMORY_MB" ] || \
  fail "available memory ${available_memory_mb}MB is below ${STAGING_MIN_AVAILABLE_MEMORY_MB}MB"
[ "$free_disk_mb" -ge "$STAGING_MIN_FREE_DISK_MB" ] || \
  fail "free disk ${free_disk_mb}MB is below ${STAGING_MIN_FREE_DISK_MB}MB"
[ "$free_inodes" -ge "$STAGING_MIN_FREE_INODES" ] || \
  fail "free inodes ${free_inodes} is below ${STAGING_MIN_FREE_INODES}"

ready_host=$(python3 -c 'import sys; from urllib.parse import urlparse; print(urlparse(sys.argv[1]).hostname or "")' "$DEPLOY_READY_URL")
[ "$ready_host" = "$STAGING_EXPECTED_MEDIA_HOST" ] || \
  fail "DEPLOY_READY_URL host must match STAGING_EXPECTED_MEDIA_HOST"

for host in "$WEB_HOST" "$ADMIN_HOST"; do
  getent ahosts "$host" >/dev/null 2>&1 || fail "DNS does not resolve: $host"
done

printf '%s\n' 'pulling all immutable Staging images...'
for image in "$ORAL_SERVER_IMAGE" "$ORAL_GATEWAY_IMAGE" "$ORAL_WEB_IMAGE" "$ORAL_ADMIN_IMAGE"; do
  docker pull "$image" >/dev/null
done

printf '%s\n' 'checking Server image runtime dependencies...'
docker run --rm "$ORAL_SERVER_IMAGE" sh -ec '
  command -v ffmpeg >/dev/null
  if command -v chromium >/dev/null; then :; elif command -v chromium-browser >/dev/null; then :; else exit 3; fi
  ffmpeg -hide_banner -filters 2>/dev/null | grep -Eq "[[:space:]]subtitles[[:space:]]"
'

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
