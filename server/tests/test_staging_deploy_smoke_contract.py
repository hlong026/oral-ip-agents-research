"""Staging deployment must be fail-closed, ordered and evidence-producing."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_staging_deploy_runs_preflight_before_migration_and_smoke_after_ready() -> None:
    script = _read("deploy/scripts/deploy-staging.sh")

    preflight = script.index("preflight-staging.sh")
    stop_old = script.index("compose stop worker server")
    migration = script.index("--profile migration run --rm --no-deps migration")
    start_new = script.index("compose up -d --remove-orphans server worker web admin gateway")
    ready = script.index('payload.get("env") == "staging"')
    smoke = script.index("staging-smoke.sh")

    assert preflight < stop_old < migration < start_new < ready < smoke
    assert "DEPLOY_ENVIRONMENT must be exactly staging" in script
    assert "checked-out commit" in script
    assert "RELEASE_GIT_COMMIT must be a 40-character Git SHA" in script
    assert "STAGING_DEPLOY_EVIDENCE_PATH" in script


def test_staging_smoke_requires_private_test_identity_and_checks_core_surfaces() -> None:
    script = _read("deploy/scripts/staging-smoke.sh")
    smoke_env = _read("deploy/staging-smoke.env.example")

    assert "STAGING_SMOKE_ENV_FILE" in script
    assert "0400 or 0600" in script
    assert "REPLACE_*" not in smoke_env
    assert "REPLACE_WITH_STAGING_TEST_ACTIVATION_CODE" in smoke_env
    assert "/readyz" not in script or "DEPLOY_READY_URL" in script
    assert "/api/v1/catalog/plans" in script
    assert "/api/v1/auth/login" in script
    assert '"deviceFingerprint"' in script
    assert 'payload.get("env") == "staging"' in script
    assert "/api/v1/auth/me" in script
    assert "compose ps --status running --services" in script
    assert "STAGING_SMOKE_EVIDENCE_PATH" in script
    assert "Authorization: Bearer" in script


def test_staging_deploy_template_separates_runtime_and_smoke_secrets() -> None:
    deploy_env = _read("deploy/.env.staging.example")
    workflow = _read(".github/workflows/production-deployment.yml")

    assert "DEPLOY_ENVIRONMENT=staging" in deploy_env
    assert "RELEASE_GIT_COMMIT=REPLACE_WITH_40_HEX_MASTER_COMMIT" in deploy_env
    assert "STAGING_SMOKE_ENV_FILE=" in deploy_env
    assert "STAGING_EVIDENCE_DIR=" in deploy_env
    assert "STAGING_WEB_URL=" in deploy_env
    assert "STAGING_ADMIN_URL=" in deploy_env
    assert "STAGING_API_BASE_URL=" in deploy_env
    assert "sh -n deploy/scripts/deploy-staging.sh" in workflow
    assert "sh -n deploy/scripts/staging-smoke.sh" in workflow
