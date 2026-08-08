"""Staging preflight must reject environment drift before network deployment."""

from pathlib import Path

from app.core.config import Settings
from scripts.staging_preflight import ExpectedIdentity, staging_identity_errors

ROOT = Path(__file__).resolve().parents[2]


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "staging",
        "storage_driver": "s3",
        "s3_bucket": "oral-staging-media-1250000000",
        "database_url": "postgresql+asyncpg://oral:secret@staging-postgres.internal.example:5432/oral_staging",
        "redis_url": "redis://:secret@staging-redis.internal.example:6379/0",
        "media_public_base_url": "https://staging-app.example.com",
        "provider_mock_fallback_enabled": False,
        "im_enabled": False,
        "publish_verified_platforms": "",
    }
    values.update(overrides)
    return Settings.model_validate(values)


def _expected(*, allow_verified_publish: bool = False) -> ExpectedIdentity:
    return ExpectedIdentity(
        bucket="oral-staging-media-1250000000",
        database_host="staging-postgres.internal.example",
        redis_host="staging-redis.internal.example",
        media_host="staging-app.example.com",
        allow_verified_publish=allow_verified_publish,
    )


def test_staging_identity_accepts_exact_allow_list() -> None:
    assert staging_identity_errors(_settings(), _expected()) == []


def test_staging_identity_rejects_environment_or_resource_drift() -> None:
    settings = _settings(
        app_env="prod",
        s3_bucket="oral-prod-media-1250000000",
        database_url="postgresql+asyncpg://oral:secret@prod-db.internal.example:5432/oral",
        redis_url="redis://:secret@prod-redis.internal.example:6379/0",
        media_public_base_url="https://app.example.com",
        im_enabled=True,
        publish_verified_platforms="douyin",
    )
    errors = staging_identity_errors(settings, _expected())
    assert "APP_ENV must be exactly staging" in errors
    assert "S3_BUCKET does not match the Staging allow-list" in errors
    assert "DATABASE_URL host does not match the Staging allow-list" in errors
    assert "REDIS_URL host does not match the Staging allow-list" in errors
    assert "MEDIA_PUBLIC_BASE_URL host does not match the Staging allow-list" in errors
    assert "IM_ENABLED must remain false during Staging infrastructure bring-up" in errors
    assert "PUBLISH_VERIFIED_PLATFORMS must stay empty unless explicitly allowed for acceptance" in errors


def test_staging_identity_allows_verified_publish_only_with_explicit_gate() -> None:
    settings = _settings(publish_verified_platforms="douyin")
    assert staging_identity_errors(settings, _expected())
    assert staging_identity_errors(settings, _expected(allow_verified_publish=True)) == []


def test_checked_in_staging_templates_are_fail_closed_placeholders() -> None:
    deploy_env = (ROOT / "deploy/.env.staging.example").read_text(encoding="utf-8")
    runtime_env = (ROOT / "server/.env.staging.example").read_text(encoding="utf-8")
    preflight = (ROOT / "deploy/scripts/preflight-staging.sh").read_text(encoding="utf-8")
    dockerfile = (ROOT / "server/Dockerfile").read_text(encoding="utf-8")

    assert "DEPLOY_ENVIRONMENT=staging" in deploy_env
    assert "STAGING_EXPECTED_COS_BUCKET=" in deploy_env
    assert "APP_ENV=staging" in runtime_env
    assert "STORAGE_DRIVER=s3" in runtime_env
    assert "PROVIDER_MOCK_FALLBACK_ENABLED=false" in runtime_env
    assert "PUBLISH_VERIFIED_PLATFORMS=\n" in runtime_env
    assert "IM_ENABLED=false" in runtime_env
    assert "REPLACE_WITH_" in runtime_env
    assert 'DEPLOY_ENVIRONMENT must be exactly staging' in preflight
    assert "@sha256:[0-9a-f]{64}" in preflight
    assert "python -m scripts.staging_preflight" in preflight
    assert "python -m scripts.staging_preflight --help" in dockerfile
