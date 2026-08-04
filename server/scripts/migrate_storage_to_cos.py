"""Command line entry point for resumable object migration to Tencent COS."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts.cos_migration import (
    MigrationConfigurationError,
    MigrationOptions,
    S3Location,
    S3Migration,
)


def _env(name: str, fallback: str = "") -> str:
    return os.environ.get(name, fallback).strip()


def _location(prefix: str, args: argparse.Namespace, *, target: bool) -> S3Location:
    lower = prefix.lower()
    endpoint = getattr(args, f"{lower}_endpoint") or _env(f"{prefix}_S3_ENDPOINT")
    region = getattr(args, f"{lower}_region") or _env(f"{prefix}_S3_REGION")
    bucket = getattr(args, f"{lower}_bucket") or _env(f"{prefix}_S3_BUCKET")
    access_key = _env(f"{prefix}_S3_ACCESS_KEY")
    secret_key = _env(f"{prefix}_S3_SECRET_KEY")
    if target:
        endpoint = endpoint or _env("S3_ENDPOINT")
        region = region or _env("S3_REGION")
        bucket = bucket or _env("S3_BUCKET")
        access_key = access_key or _env("S3_ACCESS_KEY")
        secret_key = secret_key or _env("S3_SECRET_KEY")
    return S3Location(
        endpoint_url=endpoint,
        region=region,
        bucket=bucket,
        access_key=access_key,
        secret_key=secret_key,
        addressing_style=getattr(args, f"{lower}_addressing_style"),
        signature_version=getattr(args, f"{lower}_signature_version"),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preserve object keys while migrating S3/MinIO media to Tencent COS.",
    )
    for name, default_style in (("source", "path"), ("target", "virtual")):
        parser.add_argument(f"--{name}-endpoint", default="")
        parser.add_argument(f"--{name}-region", default="")
        parser.add_argument(f"--{name}-bucket", default="")
        parser.add_argument(
            f"--{name}-addressing-style",
            choices=("virtual", "path", "auto"),
            default=default_style,
        )
        parser.add_argument(
            f"--{name}-signature-version",
            choices=("s3", "s3v4"),
            default="s3",
        )
    parser.add_argument("--prefix", default="")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("cos-migration-manifest.jsonl"),
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path("cos-migration-checkpoint.json"),
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--verify-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--sample-sha256-rate", type=float, default=0.05)
    parser.add_argument("--max-errors", type=int, default=1)
    parser.add_argument("--multipart-threshold-mb", type=int, default=64)
    parser.add_argument("--multipart-chunksize-mb", type=int, default=16)
    parser.add_argument("--max-concurrency", type=int, default=4)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        migration = S3Migration(
            source=_location("SOURCE", args, target=False),
            target=_location("TARGET", args, target=True),
            options=MigrationOptions(
                prefix=args.prefix,
                dry_run=args.dry_run,
                resume=args.resume,
                verify_only=args.verify_only,
                sample_sha256_rate=args.sample_sha256_rate,
                max_errors=args.max_errors,
                multipart_threshold_mb=args.multipart_threshold_mb,
                multipart_chunksize_mb=args.multipart_chunksize_mb,
                max_concurrency=args.max_concurrency,
            ),
            manifest_path=args.manifest,
            checkpoint_path=args.checkpoint,
        )
        migration.run()
        summary = migration.safe_summary()
    except MigrationConfigurationError as exc:
        print(
            json.dumps(
                {"ok": False, "code": "INVALID_CONFIGURATION", "message": str(exc)},
                ensure_ascii=False,
            )
        )
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"ok": False, "code": "INTERRUPTED"}, ensure_ascii=False))
        return 130
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": "MIGRATION_FAILED",
                    "errorType": type(exc).__name__,
                    "message": str(exc)[:300],
                },
                ensure_ascii=False,
            )
        )
        return 2

    ok = int(summary["stats"]["errors"]) == 0
    print(json.dumps({"ok": ok, **summary}, ensure_ascii=False, sort_keys=True))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
