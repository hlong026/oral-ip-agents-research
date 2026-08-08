"""Restore a verified custom-format backup into the explicitly allowed Staging DB."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

from sqlalchemy.engine import URL, make_url

from app.core.config import get_settings


def _pg_environment(url: URL) -> dict[str, str]:
    if not url.drivername.startswith("postgresql"):
        raise RuntimeError("DATABASE_URL must use PostgreSQL")
    if not url.host or not url.database or not url.username:
        raise RuntimeError("DATABASE_URL must include host, database and username")
    env = os.environ.copy()
    env.update(
        {
            "PGHOST": url.host,
            "PGPORT": str(url.port or 5432),
            "PGDATABASE": url.database,
            "PGUSER": url.username,
        }
    )
    if url.password:
        env["PGPASSWORD"] = url.password
    sslmode = url.query.get("sslmode") or url.query.get("ssl")
    if isinstance(sslmode, str) and sslmode:
        env["PGSSLMODE"] = sslmode
    return env


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Restore a verified dump to Staging only")
    parser.add_argument("--dump", required=True)
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--expected-database-host", required=True)
    parser.add_argument("--expected-database-name", required=True)
    parser.add_argument("--confirm", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.confirm != "RESTORE_STAGING_ONLY":
        raise SystemExit("--confirm must be RESTORE_STAGING_ONLY")

    settings = get_settings()
    if settings.app_env != "staging":
        raise SystemExit("restore is allowed only when APP_ENV=staging")

    url = make_url(settings.database_url)
    actual_host = (url.host or "").lower().rstrip(".")
    actual_name = url.database or ""
    if actual_host != args.expected_database_host.lower().rstrip("."):
        raise SystemExit("DATABASE_URL host does not match the Staging allow-list")
    if actual_name != args.expected_database_name:
        raise SystemExit("DATABASE_URL database does not match the Staging allow-list")

    dump_path = Path(args.dump).resolve()
    metadata_path = Path(args.metadata).resolve()
    if not dump_path.is_file() or not metadata_path.is_file():
        raise SystemExit("dump and metadata files must exist")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("kind") != "postgresql-backup" or metadata.get("ok") is not True:
        raise SystemExit("invalid backup metadata")
    if metadata.get("environment") != "staging":
        raise SystemExit("only a Staging backup may be restored by this tool")
    expected_sha = metadata.get("sha256")
    if not isinstance(expected_sha, str) or _sha256(dump_path) != expected_sha:
        raise SystemExit("backup SHA-256 mismatch")
    if metadata.get("dumpFile") != dump_path.name:
        raise SystemExit("backup metadata does not reference this dump file")

    pg_env = _pg_environment(url)
    subprocess.run(
        [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-acl",
            "--exit-on-error",
            "--dbname",
            actual_name,
            str(dump_path),
        ],
        check=True,
        env=pg_env,
    )
    print(json.dumps({"ok": True, "databaseHost": actual_host, "databaseName": actual_name}, sort_keys=True))


if __name__ == "__main__":
    main()
