"""Fail-closed Tencent Cloud Staging runtime preflight.

Runs inside the immutable Server image with the real Staging env file. The output
contains only non-secret resource identities and health status so it can be kept
as deployment evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from urllib.parse import urlparse

from app.core import storage
from app.core.config import Settings, get_settings, validate_runtime_security
from app.core.db import database_ready, verify_migrations_current
from app.core.events import init_redis, redis_ready


@dataclass(frozen=True)
class ExpectedIdentity:
    bucket: str
    database_host: str
    redis_host: str
    media_host: str
    allow_verified_publish: bool = False


def _url_host(value: str) -> str:
    return (urlparse(value).hostname or "").strip().lower().rstrip(".")


def staging_identity_errors(settings: Settings, expected: ExpectedIdentity) -> list[str]:
    """Return non-secret identity mismatches that could indicate a wrong environment."""
    errors: list[str] = []
    if settings.app_env != "staging":
        errors.append("APP_ENV must be exactly staging")
    if settings.storage_driver != "s3":
        errors.append("STORAGE_DRIVER must be s3")
    if settings.s3_bucket != expected.bucket:
        errors.append("S3_BUCKET does not match the Staging allow-list")
    if _url_host(settings.database_url) != expected.database_host.lower().rstrip("."):
        errors.append("DATABASE_URL host does not match the Staging allow-list")
    if _url_host(settings.redis_url) != expected.redis_host.lower().rstrip("."):
        errors.append("REDIS_URL host does not match the Staging allow-list")
    if _url_host(settings.media_public_base_url) != expected.media_host.lower().rstrip("."):
        errors.append("MEDIA_PUBLIC_BASE_URL host does not match the Staging allow-list")
    if settings.im_enabled:
        errors.append("IM_ENABLED must remain false during Staging infrastructure bring-up")
    if settings.publish_verified_platforms.strip() and not expected.allow_verified_publish:
        errors.append("PUBLISH_VERIFIED_PLATFORMS must stay empty unless explicitly allowed for acceptance")
    if settings.mock_fallback_allowed:
        errors.append("provider Mock fallback must be disabled in Staging")
    return errors


async def run_live_checks(settings: Settings) -> tuple[bool, dict[str, object]]:
    """Probe migrations, DB, Redis and COS, including a fixed-key COS write/read check."""
    result: dict[str, object] = {
        "database": {"ok": False},
        "redis": {"ok": False},
        "storage": {"ok": False},
        "migration": {"ok": False},
        "cosWriteRead": {"ok": False},
    }

    try:
        await verify_migrations_current()
        result["migration"] = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        result["migration"] = {"ok": False, "errorType": type(exc).__name__}

    try:
        result["database"] = {"ok": bool(await database_ready())}
    except Exception as exc:  # noqa: BLE001
        result["database"] = {"ok": False, "errorType": type(exc).__name__}

    try:
        await init_redis(settings.redis_url)
        result["redis"] = {"ok": bool(await redis_ready())}
    except Exception as exc:  # noqa: BLE001
        result["redis"] = {"ok": False, "errorType": type(exc).__name__}

    storage_status = await storage.storage_readiness()
    result["storage"] = storage_status

    if storage_status.get("ok"):
        probe_key = "ops/preflight/staging-runtime-v1.txt"
        probe_body = b"oral-staging-preflight-v1"
        try:
            client = storage._s3_client()  # noqa: SLF001 - operations probe intentionally uses the configured client.
            await asyncio.to_thread(
                client.put_object,
                Bucket=settings.s3_bucket,
                Key=probe_key,
                Body=probe_body,
                ContentType="text/plain",
            )
            obj = await asyncio.to_thread(client.get_object, Bucket=settings.s3_bucket, Key=probe_key)
            body = await asyncio.to_thread(obj["Body"].read)
            result["cosWriteRead"] = {"ok": body == probe_body, "key": probe_key}
        except Exception as exc:  # noqa: BLE001
            result["cosWriteRead"] = {"ok": False, "errorType": type(exc).__name__}

    ok = all(bool(status.get("ok")) for status in result.values() if isinstance(status, dict))
    return ok, result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate the real Tencent Cloud Staging runtime before deployment")
    parser.add_argument("--expected-bucket", required=True)
    parser.add_argument("--expected-database-host", required=True)
    parser.add_argument("--expected-redis-host", required=True)
    parser.add_argument("--expected-media-host", required=True)
    parser.add_argument("--allow-verified-publish", action="store_true")
    return parser


async def async_main() -> int:
    args = build_parser().parse_args()
    settings = get_settings()
    expected = ExpectedIdentity(
        bucket=args.expected_bucket,
        database_host=args.expected_database_host,
        redis_host=args.expected_redis_host,
        media_host=args.expected_media_host,
        allow_verified_publish=args.allow_verified_publish,
    )

    errors: list[str] = []
    try:
        validate_runtime_security(settings)
    except RuntimeError as exc:
        errors.append(str(exc))
    errors.extend(staging_identity_errors(settings, expected))

    evidence: dict[str, object] = {
        "ok": False,
        "env": settings.app_env,
        "identity": {
            "bucket": settings.s3_bucket,
            "region": settings.s3_region,
            "endpointHost": _url_host(settings.s3_endpoint),
            "databaseHost": _url_host(settings.database_url),
            "redisHost": _url_host(settings.redis_url),
            "mediaHost": _url_host(settings.media_public_base_url),
        },
        "configurationErrors": errors,
    }
    if errors:
        print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
        return 2

    live_ok, checks = await run_live_checks(settings)
    evidence["checks"] = checks
    evidence["ok"] = live_ok
    print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0 if live_ok else 3


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
