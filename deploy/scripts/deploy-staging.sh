#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
DEPLOY_ENV=${1:-"$ROOT_DIR/deploy/.env.staging"}
COMPOSE_FILE="$ROOT_DIR/docker-compose.prod.yml"

fail() {
  printf 'staging deploy error: %s\n' "$*" >&2
  exit 2
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"
}

[ -f "$DEPLOY_ENV" ] || fail "deployment env not found: $DEPLOY_ENV"
require_command curl
require_command docker
require_command git
require_command grep
require_command python3

set -a
# shellcheck disable=SC1090
. "$DEPLOY_ENV"
set +a

[ "${DEPLOY_ENVIRONMENT:-}" = "staging" ] || fail "DEPLOY_ENVIRONMENT must be exactly staging"
: "${RELEASE_GIT_COMMIT:?RELEASE_GIT_COMMIT is required}"
: "${DEPLOY_READY_URL:?DEPLOY_READY_URL is required}"
: "${STAGING_EVIDENCE_DIR:?STAGING_EVIDENCE_DIR is required}"
: "${ORAL_SERVER_IMAGE:?ORAL_SERVER_IMAGE is required}"
: "${ORAL_GATEWAY_IMAGE:?ORAL_GATEWAY_IMAGE is required}"
: "${ORAL_WEB_IMAGE:?ORAL_WEB_IMAGE is required}"
: "${ORAL_ADMIN_IMAGE:?ORAL_ADMIN_IMAGE is required}"
printf '%s' "$RELEASE_GIT_COMMIT" | grep -Eq '^[0-9a-f]{40}$' || fail "RELEASE_GIT_COMMIT must be a 40-character Git SHA"

checked_out_commit=$(git -C "$ROOT_DIR" rev-parse HEAD)
[ "$checked_out_commit" = "$RELEASE_GIT_COMMIT" ] || \
  fail "checked-out commit $checked_out_commit does not match RELEASE_GIT_COMMIT"

compose() {
  docker compose --env-file "$DEPLOY_ENV" -f "$COMPOSE_FILE" "$@"
}

printf '%s\n' '1/7 running fail-closed Staging preflight...'
"$ROOT_DIR/deploy/scripts/preflight-staging.sh" "$DEPLOY_ENV"

printf '%s\n' '2/7 validating Staging compose...'
compose config --quiet

printf '%s\n' '3/7 stopping old API and Worker before schema migration...'
compose stop worker server || true

printf '%s\n' '4/7 running database migration with the release Server image...'
compose --profile migration run --rm --no-deps migration

printf '%s\n' '5/7 starting Staging application services...'
compose up -d --remove-orphans server worker web admin gateway

printf '%s\n' '6/7 waiting for Staging /readyz...'
attempt=0
while :; do
  attempt=$((attempt + 1))
  if payload=$(curl --fail --silent --show-error --max-time 10 "$DEPLOY_READY_URL" 2>/dev/null); then
    if printf '%s' "$payload" | python3 -c '
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
'; then
      break
    fi
  fi
  [ "$attempt" -lt "${DEPLOY_READY_ATTEMPTS:-30}" ] || fail "Staging readyz did not become healthy"
  sleep "${DEPLOY_READY_INTERVAL_SECONDS:-5}"
done

printf '%s\n' '7/7 running authenticated Staging smoke...'
"$ROOT_DIR/deploy/scripts/staging-smoke.sh" "$DEPLOY_ENV"

mkdir -p "$STAGING_EVIDENCE_DIR"
chmod 700 "$STAGING_EVIDENCE_DIR"
deploy_evidence="$STAGING_EVIDENCE_DIR/deploy-${RELEASE_GIT_COMMIT}.json"
export STAGING_DEPLOY_EVIDENCE_PATH="$deploy_evidence"
python3 -c '
import datetime, json, os
payload = {
    "schemaVersion": 1,
    "kind": "staging-deploy",
    "ok": True,
    "gitCommit": os.environ["RELEASE_GIT_COMMIT"],
    "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
    "images": {
        "server": os.environ["ORAL_SERVER_IMAGE"],
        "gateway": os.environ["ORAL_GATEWAY_IMAGE"],
        "web": os.environ["ORAL_WEB_IMAGE"],
        "admin": os.environ["ORAL_ADMIN_IMAGE"],
    },
    "storage": {
        "bucket": os.environ["STAGING_EXPECTED_COS_BUCKET"],
    },
    "endpoints": {
        "readyz": os.environ["DEPLOY_READY_URL"],
        "web": os.environ["STAGING_WEB_URL"],
        "admin": os.environ["STAGING_ADMIN_URL"],
        "api": os.environ["STAGING_API_BASE_URL"],
    },
    "smokeEvidence": os.path.join(
        os.environ["STAGING_EVIDENCE_DIR"],
        "smoke-{}.json".format(os.environ["RELEASE_GIT_COMMIT"]),
    ),
}
with open(os.environ["STAGING_DEPLOY_EVIDENCE_PATH"], "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
    handle.write("\n")
'
chmod 600 "$deploy_evidence"
compose ps
printf 'Staging deployment accepted; evidence: %s\n' "$deploy_evidence"
