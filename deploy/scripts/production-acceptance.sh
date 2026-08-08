#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
DEPLOY_ENV=${1:-"$ROOT_DIR/deploy/.env.staging"}

fail() {
  printf 'production acceptance error: %s\n' "$*" >&2
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
command -v git >/dev/null 2>&1 || fail "missing command: git"
command -v grep >/dev/null 2>&1 || fail "missing command: grep"
command -v python3 >/dev/null 2>&1 || fail "missing command: python3"
command -v stat >/dev/null 2>&1 || fail "missing command: stat"
require_private_file DEPLOY_ENV "$DEPLOY_ENV"

set -a
# shellcheck disable=SC1090
. "$DEPLOY_ENV"
set +a

[ "${DEPLOY_ENVIRONMENT:-}" = "staging" ] || fail "Production acceptance must run against DEPLOY_ENVIRONMENT=staging"
: "${RELEASE_GIT_COMMIT:?RELEASE_GIT_COMMIT is required}"
: "${STAGING_EVIDENCE_DIR:?STAGING_EVIDENCE_DIR is required}"
: "${STAGING_MANUAL_ACCEPTANCE_RESULTS:?STAGING_MANUAL_ACCEPTANCE_RESULTS is required}"
printf '%s' "$RELEASE_GIT_COMMIT" | grep -Eq '^[0-9a-f]{40}$' || fail "RELEASE_GIT_COMMIT must be a 40-character Git SHA"
require_private_file STAGING_MANUAL_ACCEPTANCE_RESULTS "$STAGING_MANUAL_ACCEPTANCE_RESULTS"

checked_out_commit=$(git -C "$ROOT_DIR" rev-parse HEAD)
[ "$checked_out_commit" = "$RELEASE_GIT_COMMIT" ] || \
  fail "checked-out commit $checked_out_commit does not match RELEASE_GIT_COMMIT"

mkdir -p "$STAGING_EVIDENCE_DIR"
chmod 700 "$STAGING_EVIDENCE_DIR"
output="$STAGING_EVIDENCE_DIR/acceptance-${RELEASE_GIT_COMMIT}.json"

printf '%s\n' 'refreshing authenticated Staging smoke before Go/No-Go evaluation...'
sh "$ROOT_DIR/deploy/scripts/staging-smoke.sh" "$DEPLOY_ENV"

printf '%s\n' 'building fail-closed Production acceptance report...'
set +e
python3 "$ROOT_DIR/server/scripts/acceptance_report.py" \
  --cases "$ROOT_DIR/deploy/acceptance/acceptance-cases.json" \
  --evidence-dir "$STAGING_EVIDENCE_DIR" \
  --manual-results "$STAGING_MANUAL_ACCEPTANCE_RESULTS" \
  --git-commit "$RELEASE_GIT_COMMIT" \
  --output "$output"
status=$?
set -e

if [ "$status" -eq 0 ]; then
  printf 'Production acceptance decision: GO; report: %s\n' "$output"
  exit 0
fi
if [ "$status" -eq 3 ]; then
  printf 'Production acceptance decision: NO_GO; report: %s\n' "$output" >&2
  exit 3
fi
fail "acceptance report engine failed with exit code $status"
