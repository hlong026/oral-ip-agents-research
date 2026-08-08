"""Staging Actions must deploy only from a protected Tencent Cloud runner."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_staging_workflow_is_manual_read_only_and_environment_protected() -> None:
    workflow = _read(".github/workflows/staging-deployment.yml")

    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "push:" not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "environment: staging" in workflow
    assert "runs-on: [self-hosted, linux, oral-staging]" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "secrets." not in workflow


def test_staging_workflow_pins_a_commit_merged_into_master() -> None:
    workflow = _read(".github/workflows/staging-deployment.yml")

    assert "40-character commit already merged into master" in workflow
    assert '[[ "$REQUESTED_COMMIT" =~ ^[0-9a-f]{40}$ ]]' in workflow
    assert "git fetch --no-tags origin +refs/heads/master:refs/remotes/origin/master" in workflow
    assert 'git merge-base --is-ancestor "$actual" refs/remotes/origin/master' in workflow
    assert '[[ "${RELEASE_GIT_COMMIT:-}" == "$REQUESTED_COMMIT" ]]' in workflow


def test_staging_workflow_runs_deploy_backup_and_optional_fail_closed_acceptance() -> None:
    workflow = _read(".github/workflows/staging-deployment.yml")

    deploy = workflow.index('sh deploy/scripts/deploy-staging.sh "$STAGING_DEPLOY_ENV"')
    backup = workflow.index('sh deploy/scripts/backup-database.sh "$STAGING_DEPLOY_ENV"')
    acceptance = workflow.index('sh deploy/scripts/production-acceptance.sh "$STAGING_DEPLOY_ENV"')

    assert deploy < backup < acceptance
    assert "if: ${{ inputs.run_acceptance }}" in workflow
    assert "STAGING_DEPLOY_ENV: /etc/oral/staging-deploy.env" in workflow
    assert "runtime and smoke files must live under /etc/oral" in workflow
    assert "manual acceptance results must live under /etc/oral" in workflow


def test_staging_artifact_export_excludes_database_dump_and_private_envs() -> None:
    workflow = _read(".github/workflows/staging-deployment.yml")
    evidence_readme = _read("evidence/staging/README.md")

    assert "actions/upload-artifact@v4" in workflow
    assert "staging-evidence-${{ inputs.git_commit }}" in workflow
    assert "-name 'db-*.json'" in workflow
    assert ".dump" not in workflow
    assert "/etc/oral/*.env" in evidence_readme
    assert "PostgreSQL `.dump`" in evidence_readme
    assert "不得进入 GitHub Artifact" in evidence_readme


def test_nested_staging_shells_do_not_require_executable_file_mode() -> None:
    deploy = _read("deploy/scripts/deploy-staging.sh")
    restore = _read("deploy/scripts/restore-database-staging.sh")
    acceptance = _read("deploy/scripts/production-acceptance.sh")

    assert 'sh "$ROOT_DIR/deploy/scripts/preflight-staging.sh"' in deploy
    assert 'sh "$ROOT_DIR/deploy/scripts/staging-smoke.sh"' in deploy
    assert 'sh "$ROOT_DIR/deploy/scripts/staging-smoke.sh"' in restore
    assert 'sh "$ROOT_DIR/deploy/scripts/staging-smoke.sh"' in acceptance


def test_production_deployment_gate_is_triggered_by_staging_workflow_changes() -> None:
    gate = _read(".github/workflows/production-deployment.yml")

    assert gate.count(".github/workflows/staging-deployment.yml") == 2
