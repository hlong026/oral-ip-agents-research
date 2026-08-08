#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
DEPLOY_ENV=${1:-"$ROOT_DIR/deploy/.env.staging"}
COMPOSE_FILE="$ROOT_DIR/docker-compose.prod.yml"

fail() {
  printf 'staging smoke error: %s\n' "$*" >&2
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

[ -f "$DEPLOY_ENV" ] || fail "deployment env not found: $DEPLOY_ENV"
require_command curl
require_command docker
require_command grep
require_command python3
require_command stat

set -a
# shellcheck disable=SC1090
. "$DEPLOY_ENV"
set +a

[ "${DEPLOY_ENVIRONMENT:-}" = "staging" ] || fail "DEPLOY_ENVIRONMENT must be exactly staging"
: "${STAGING_SMOKE_ENV_FILE:?STAGING_SMOKE_ENV_FILE is required}"
: "${STAGING_EVIDENCE_DIR:?STAGING_EVIDENCE_DIR is required}"
: "${STAGING_WEB_URL:?STAGING_WEB_URL is required}"
: "${STAGING_ADMIN_URL:?STAGING_ADMIN_URL is required}"
: "${STAGING_API_BASE_URL:?STAGING_API_BASE_URL is required}"
: "${DEPLOY_READY_URL:?DEPLOY_READY_URL is required}"
: "${RELEASE_GIT_COMMIT:?RELEASE_GIT_COMMIT is required}"
require_private_file STAGING_SMOKE_ENV_FILE "$STAGING_SMOKE_ENV_FILE"

set -a
# shellcheck disable=SC1090
. "$STAGING_SMOKE_ENV_FILE"
set +a

: "${STAGING_SMOKE_ACTIVATION_CODE:?STAGING_SMOKE_ACTIVATION_CODE is required}"
: "${STAGING_SMOKE_DEVICE_FINGERPRINT:?STAGING_SMOKE_DEVICE_FINGERPRINT is required}"
case "$STAGING_SMOKE_ACTIVATION_CODE" in
  REPLACE_*) fail "replace the Staging smoke activation code" ;;
esac
printf '%s' "$RELEASE_GIT_COMMIT" | grep -Eq '^[0-9a-f]{40}$' || fail "RELEASE_GIT_COMMIT must be a 40-character Git SHA"

compose() {
  docker compose --env-file "$DEPLOY_ENV" -f "$COMPOSE_FILE" "$@"
}

printf '%s\n' '1/6 checking Gateway/API readiness...'
ready_payload=$(curl --fail --silent --show-error --max-time 15 "$DEPLOY_READY_URL")
printf '%s' "$ready_payload" | python3 -c '
import json, sys
payload = json.load(sys.stdin)
assert payload.get("ok") is True, payload
assert payload.get("env") == "staging", payload
deps = payload.get("dependencies", {})
assert deps.get("database", {}).get("ok") is True, deps
assert deps.get("redis", {}).get("ok") is True, deps
storage = deps.get("storage", {})
assert storage.get("ok") is True, storage
assert storage.get("driver") == "s3", storage
'

printf '%s\n' '2/6 checking Web SPA...'
curl --fail --location --silent --show-error --max-time 15 --output /dev/null "$STAGING_WEB_URL/"

printf '%s\n' '3/6 checking Admin SPA...'
curl --fail --location --silent --show-error --max-time 15 --output /dev/null "$STAGING_ADMIN_URL/"

printf '%s\n' '4/6 checking public API path...'
curl --fail --silent --show-error --max-time 15 --output /dev/null "$STAGING_API_BASE_URL/api/v1/catalog/plans"

printf '%s\n' '5/6 checking dedicated Staging account login...'
login_body=$(python3 -c '
import json, os
print(json.dumps({
    "code": os.environ["STAGING_SMOKE_ACTIVATION_CODE"],
    "deviceFingerprint": os.environ["STAGING_SMOKE_DEVICE_FINGERPRINT"],
}))
')
login_response=$(printf '%s' "$login_body" | curl \
  --fail --silent --show-error --max-time 15 \
  --header 'Content-Type: application/json' \
  --data-binary @- \
  "$STAGING_API_BASE_URL/api/v1/auth/login")
access_token=$(printf '%s' "$login_response" | python3 -c '
import json, sys
payload = json.load(sys.stdin)
token = payload.get("accessToken")
assert isinstance(token, str) and token, payload
print(token)
')
printf 'header = "Authorization: Bearer %s"\n' "$access_token" | curl \
  --config - \
  --fail --silent --show-error --max-time 15 --output /dev/null \
  "$STAGING_API_BASE_URL/api/v1/auth/me"
unset access_token login_body login_response STAGING_SMOKE_ACTIVATION_CODE

printf '%s\n' '6/6 checking Worker process and writing smoke evidence...'
compose ps --status running --services | grep -qx 'worker' || fail "worker service is not running"
mkdir -p "$STAGING_EVIDENCE_DIR"
chmod 700 "$STAGING_EVIDENCE_DIR"
evidence_path="$STAGING_EVIDENCE_DIR/smoke-${RELEASE_GIT_COMMIT}.json"
export STAGING_SMOKE_EVIDENCE_PATH="$evidence_path"
python3 -c '
import datetime, json, os
payload = {
    "schemaVersion": 1,
    "kind": "staging-smoke",
    "ok": True,
    "gitCommit": os.environ["RELEASE_GIT_COMMIT"],
    "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
    "checks": {
        "readyz": True,
        "web": True,
        "admin": True,
        "publicApi": True,
        "authenticatedUser": True,
        "workerRunning": True,
    },
    "endpoints": {
        "web": os.environ["STAGING_WEB_URL"],
        "admin": os.environ["STAGING_ADMIN_URL"],
        "api": os.environ["STAGING_API_BASE_URL"],
    },
}
with open(os.environ["STAGING_SMOKE_EVIDENCE_PATH"], "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
    handle.write("\n")
'
chmod 600 "$evidence_path"
printf 'staging smoke passed; evidence: %s\n' "$evidence_path"
