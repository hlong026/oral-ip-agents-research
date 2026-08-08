#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
DEPLOY_ENV=${1:-"$ROOT_DIR/deploy/.env.staging"}

fail() {
  printf 'database backup error: %s\n' "$*" >&2
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

require_immutable_image() {
  name=$1
  value=$2
  printf '%s' "$value" | grep -Eq '@sha256:[0-9a-f]{64}$' || fail "$name must use an immutable @sha256 digest"
}

[ -f "$DEPLOY_ENV" ] || fail "deployment env not found: $DEPLOY_ENV"
command -v docker >/dev/null 2>&1 || fail "missing command: docker"
command -v grep >/dev/null 2>&1 || fail "missing command: grep"
command -v id >/dev/null 2>&1 || fail "missing command: id"
command -v stat >/dev/null 2>&1 || fail "missing command: stat"
require_private_file DEPLOY_ENV "$DEPLOY_ENV"

set -a
# shellcheck disable=SC1090
. "$DEPLOY_ENV"
set +a

: "${DEPLOY_ENVIRONMENT:?DEPLOY_ENVIRONMENT is required}"
: "${RELEASE_GIT_COMMIT:?RELEASE_GIT_COMMIT is required}"
: "${ORAL_SERVER_IMAGE:?ORAL_SERVER_IMAGE is required}"
: "${ORAL_ENV_FILE:?ORAL_ENV_FILE is required}"
printf '%s' "$RELEASE_GIT_COMMIT" | grep -Eq '^[0-9a-f]{40}$' || fail "RELEASE_GIT_COMMIT must be a 40-character Git SHA"
require_immutable_image ORAL_SERVER_IMAGE "$ORAL_SERVER_IMAGE"
require_private_file ORAL_ENV_FILE "$ORAL_ENV_FILE"

case "$DEPLOY_ENVIRONMENT" in
  staging)
    : "${STAGING_BACKUP_DIR:?STAGING_BACKUP_DIR is required}"
    backup_dir=$STAGING_BACKUP_DIR
    docker_network=${STAGING_DOCKER_NETWORK:-}
    ;;
  production)
    : "${PRODUCTION_BACKUP_DIR:?PRODUCTION_BACKUP_DIR is required}"
    backup_dir=$PRODUCTION_BACKUP_DIR
    docker_network=${PRODUCTION_DOCKER_NETWORK:-}
    ;;
  *) fail "DEPLOY_ENVIRONMENT must be staging or production" ;;
esac

mkdir -p "$backup_dir"
chmod 700 "$backup_dir"
backup_dir=$(CDPATH= cd -- "$backup_dir" && pwd)
docker pull "$ORAL_SERVER_IMAGE" >/dev/null

set -- docker run --rm --user "$(id -u):$(id -g)"
if [ -n "$docker_network" ]; then
  set -- "$@" --network "$docker_network"
fi
set -- "$@" \
  --env-file "$ORAL_ENV_FILE" \
  --volume "$backup_dir:/backup" \
  "$ORAL_SERVER_IMAGE" \
  python -m scripts.database_backup \
  --output-dir /backup \
  --git-commit "$RELEASE_GIT_COMMIT"

"$@"
printf 'database backup complete; private backup directory: %s\n' "$backup_dir"
