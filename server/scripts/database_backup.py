"""Create a private PostgreSQL custom-format dump with non-secret metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import URL, make_url

from app.core.config import get_settings

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


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


def _alembic_revisions(pg_env: dict[str, str]) -> list[str]:
    result = subprocess.run(
        [
            "psql",
            "--no-align",
            "--tuples-only",
            "--command",
            "SELECT version_num FROM alembic_version ORDER BY version_num",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=pg_env,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a PostgreSQL backup and SHA-256 evidence")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--git-commit", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not _GIT_SHA_RE.fullmatch(args.git_commit):
        raise SystemExit("--git-commit must be a 40-character lowercase Git SHA")

    settings = get_settings()
    if settings.app_env not in {"staging", "prod"}:
        raise SystemExit("database backup is allowed only for staging or prod")

    url = make_url(settings.database_url)
    pg_env = _pg_environment(url)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir.chmod(0o700)
    os.umask(0o077)

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stem = f"db-{args.git_commit[:12]}-{timestamp}"
    dump_path = output_dir / f"{stem}.dump"
    metadata_path = output_dir / f"{stem}.json"
    if dump_path.exists() or metadata_path.exists():
        raise SystemExit("backup output already exists; refusing to overwrite")

    subprocess.run(
        [
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--no-acl",
            "--file",
            str(dump_path),
        ],
        check=True,
        env=pg_env,
    )
    dump_path.chmod(0o600)

    digest = _sha256(dump_path)
    revisions = _alembic_revisions(pg_env)
    metadata = {
        "schemaVersion": 1,
        "kind": "postgresql-backup",
        "ok": True,
        "environment": settings.app_env,
        "gitCommit": args.git_commit,
        "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "database": {
            "host": url.host,
            "port": url.port or 5432,
            "name": url.database,
            "alembicRevisions": revisions,
        },
        "dumpFile": dump_path.name,
        "bytes": dump_path.stat().st_size,
        "sha256": digest,
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    metadata_path.chmod(0o600)

    print(
        json.dumps(
            {
                "ok": True,
                "dumpFile": str(dump_path),
                "metadataFile": str(metadata_path),
                "sha256": digest,
                "bytes": dump_path.stat().st_size,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
