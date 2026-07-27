"""Production startup guards."""

import pytest

from app.core.config import Settings, validate_runtime_security


def valid_production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "prod",
        "app_secret": "a" * 32,
        "config_encryption_key": "b" * 32,
        "activation_secret": "c" * 32,
        "publish_session_encryption_key": "d" * 32,
        "feiying_webhook_secret": "e" * 32,
        "database_url": "postgresql+asyncpg://oral:password@db:5432/oral",
        "redis_url": "redis://redis:6379/0",
        "cors_origins": "https://app.oral.company,https://admin.oral.company",
        "storage_driver": "s3",
        "s3_endpoint": "https://minio.oral.company",
        "s3_access_key": "production-access-key",
        "s3_secret_key": "f" * 32,
        "s3_bucket": "oral-media",
        "media_public_base_url": "https://api.oral.company",
        "publish_browser_headless": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_im_feature_is_disabled_by_default() -> None:
    from app.core.config import get_settings
    from app.main import app

    assert get_settings().im_enabled is False
    assert all(not getattr(route, "path", "").startswith("/api/v1/im") for route in app.routes)


async def test_init_models_skips_create_all_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import db

    class ForbiddenEngine:
        def begin(self):
            raise AssertionError("production startup must not invoke create_all")

    monkeypatch.setattr(db.settings, "app_env", "prod")
    monkeypatch.setattr(db, "engine", ForbiddenEngine())

    await db.init_models()


def test_production_requires_webhook_signature_secret() -> None:
    settings = valid_production_settings(feiying_webhook_secret="")

    with pytest.raises(RuntimeError, match="FEIYING_WEBHOOK_SECRET"):
        validate_runtime_security(settings)


def test_production_rejects_im_until_compliance_go() -> None:
    settings = valid_production_settings(im_enabled=True)

    with pytest.raises(RuntimeError, match="第三阶段合规结论为 No-Go"):
        validate_runtime_security(settings)


def test_enabled_im_requires_real_provider_key_even_in_test() -> None:
    settings = Settings(app_env="test", im_enabled=True, douyin_im_app_key="")

    with pytest.raises(RuntimeError, match="DOUYIN_IM_APP_KEY"):
        validate_runtime_security(settings)


def test_valid_production_configuration_passes_runtime_guard() -> None:
    validate_runtime_security(valid_production_settings())


def test_production_allows_only_fixed_tauri_desktop_origins() -> None:
    validate_runtime_security(
        valid_production_settings(cors_origins=("https://app.oral.company,tauri://localhost,https://tauri.localhost"))
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("app_secret", "short"),
        ("config_encryption_key", "REPLACE_WITH_PROVIDER_KEY"),
        ("activation_secret", "change-me-in-production"),
        ("publish_session_encryption_key", ""),
        ("feiying_webhook_secret", "short"),
    ],
)
def test_production_rejects_weak_or_placeholder_secrets(field: str, value: str) -> None:
    settings = valid_production_settings(**{field: value})

    with pytest.raises(RuntimeError, match=field.upper()):
        validate_runtime_security(settings)


def test_production_requires_distinct_application_secrets() -> None:
    settings = valid_production_settings(activation_secret="a" * 32)

    with pytest.raises(RuntimeError, match="互不相同"):
        validate_runtime_security(settings)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"database_url": "sqlite+aiosqlite:///./oral.db"}, "DATABASE_URL"),
        ({"redis_url": ""}, "REDIS_URL"),
        ({"cors_origins": ""}, "CORS_ORIGINS"),
        ({"cors_origins": "http://app.example.com"}, "CORS_ORIGINS"),
        ({"cors_origins": "electron://localhost"}, "CORS_ORIGINS"),
        ({"cors_origins": "https://"}, "CORS_ORIGINS"),
        ({"cors_origins": "https://localhost"}, "CORS_ORIGINS"),
        ({"cors_origins": "https://127.0.0.1"}, "CORS_ORIGINS"),
        ({"cors_origins": "https://10.0.0.8"}, "CORS_ORIGINS"),
        ({"cors_origins": "https://app.internal"}, "CORS_ORIGINS"),
        ({"cors_origins": "https://app.example"}, "CORS_ORIGINS"),
        ({"cors_origins": "https://oral-web"}, "CORS_ORIGINS"),
        ({"storage_driver": "local"}, "STORAGE_DRIVER"),
        ({"s3_endpoint": ""}, "S3_ENDPOINT"),
        ({"s3_endpoint": "https://"}, "S3_ENDPOINT"),
        ({"s3_access_key": "REPLACE_S3_ACCESS_KEY"}, "S3_ACCESS_KEY"),
        ({"s3_secret_key": "short"}, "S3_SECRET_KEY"),
        ({"s3_bucket": ""}, "S3_BUCKET"),
        ({"media_public_base_url": ""}, "MEDIA_PUBLIC_BASE_URL"),
        ({"media_public_base_url": "http://api.example.com"}, "MEDIA_PUBLIC_BASE_URL"),
        ({"media_public_base_url": "https://"}, "MEDIA_PUBLIC_BASE_URL"),
        ({"media_public_base_url": "https://localhost"}, "MEDIA_PUBLIC_BASE_URL"),
        ({"media_public_base_url": "https://127.0.0.1"}, "MEDIA_PUBLIC_BASE_URL"),
        ({"media_public_base_url": "https://192.168.1.8"}, "MEDIA_PUBLIC_BASE_URL"),
        ({"media_public_base_url": "https://media.internal"}, "MEDIA_PUBLIC_BASE_URL"),
        ({"media_public_base_url": "https://media.example"}, "MEDIA_PUBLIC_BASE_URL"),
        ({"media_public_base_url": "https://oral-media"}, "MEDIA_PUBLIC_BASE_URL"),
        ({"publish_browser_headless": False}, "PUBLISH_BROWSER_HEADLESS"),
    ],
)
def test_production_rejects_unsafe_infrastructure_configuration(
    overrides: dict[str, object],
    expected: str,
) -> None:
    settings = valid_production_settings(**overrides)

    with pytest.raises(RuntimeError, match=expected):
        validate_runtime_security(settings)
