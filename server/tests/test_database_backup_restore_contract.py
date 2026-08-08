"""Database backup/restore tooling must not leak credentials or target Production restore."""

from pathlib import Path

from sqlalchemy.engine import make_url

from scripts.database_backup import _pg_environment

ROOT = Path(__file__).resolve().parents[2]


def test_pg_environment_keeps_password_out_of_connection_arguments() -> None:
    url = make_url("postgresql+asyncpg://oral:super-secret@staging-db.internal:5432/oral_staging?sslmode=require")
    env = _pg_environment(url)

    assert env["PGHOST"] == "staging-db.internal"
    assert env["PGDATABASE"] == "oral_staging"
    assert env["PGUSER"] == "oral"
    assert env["PGPASSWORD"] == "super-secret"
    assert env["PGSSLMODE"] == "require"


def test_restore_wrapper_is_staging_only_and_stops_workers_before_pg_restore() -> None:
    script = (ROOT / "deploy/scripts/restore-database-staging.sh").read_text(encoding="utf-8")

    assert "RESTORE_STAGING_ONLY" in script
    assert "restore is allowed only for DEPLOY_ENVIRONMENT=staging" in script
    assert "STAGING_EXPECTED_DATABASE_HOST" in script
    assert "STAGING_EXPECTED_DATABASE_NAME" in script
    assert "@sha256:[0-9a-f]{64}" in script
    assert script.index("compose stop worker server") < script.index("database_restore_staging")
    assert script.index("database_restore_staging") < script.index("--profile migration run --rm --no-deps migration")
    assert script.index("--profile migration run --rm --no-deps migration") < script.index("compose up -d server worker")
    assert "staging-smoke.sh" in script
    assert "alembic downgrade" not in script


def test_backup_wrapper_supports_prod_backup_but_never_restore() -> None:
    backup = (ROOT / "deploy/scripts/backup-database.sh").read_text(encoding="utf-8")
    restore = (ROOT / "deploy/scripts/restore-database-staging.sh").read_text(encoding="utf-8")

    assert "production)" in backup
    assert "PRODUCTION_BACKUP_DIR" in backup
    assert "--user \"$(id -u):$(id -g)\"" in backup
    assert "production" not in restore.lower().split("restore is allowed only", 1)[1]


def test_backup_metadata_code_never_serializes_database_password() -> None:
    source = (ROOT / "server/scripts/database_backup.py").read_text(encoding="utf-8")

    assert '"password"' not in source
    assert 'env["PGPASSWORD"] = url.password' in source
    assert '"host": url.host' in source
    assert '"name": url.database' in source
    assert '"sha256": digest' in source
