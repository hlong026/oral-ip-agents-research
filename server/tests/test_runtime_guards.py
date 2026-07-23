"""Production startup guards."""

import pytest

from app.core.config import Settings, validate_runtime_security


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
    settings = Settings(
        app_env="prod",
        app_secret="production-app-secret",
        config_encryption_key="provider-config-key",
        activation_secret="activation-key",
        publish_session_encryption_key="publish-session-key",
        feiying_webhook_secret="",
    )

    with pytest.raises(RuntimeError, match="FEIYING_WEBHOOK_SECRET"):
        validate_runtime_security(settings)


def test_production_rejects_short_security_secrets() -> None:
    settings = Settings(
        app_env="production",
        app_secret="short",
        config_encryption_key="c" * 32,
        activation_secret="a" * 32,
        publish_session_encryption_key="p" * 32,
        feiying_webhook_secret="w" * 32,
    )

    with pytest.raises(RuntimeError, match="APP_SECRET"):
        validate_runtime_security(settings)


def test_production_rejects_reused_security_secrets() -> None:
    reused = "r" * 32
    settings = Settings(
        app_env="production",
        app_secret=reused,
        admin_jwt_secret="j" * 32,
        config_encryption_key=reused,
        activation_secret="a" * 32,
        publish_session_encryption_key="p" * 32,
        feiying_webhook_secret="w" * 32,
    )

    with pytest.raises(RuntimeError, match="不得复用"):
        validate_runtime_security(settings)


def test_runtime_rejects_unapproved_jwt_algorithm() -> None:
    settings = Settings(app_env="test", jwt_algorithm="none")

    with pytest.raises(RuntimeError, match="JWT_ALGORITHM"):
        validate_runtime_security(settings)


def _production_settings(**overrides: object) -> Settings:
    base = {
        "app_env": "production",
        "app_secret": "a" * 32,
        "admin_jwt_secret": "j" * 32,
        "config_encryption_key": "c" * 32,
        "activation_secret": "b" * 32,
        "publish_session_encryption_key": "p" * 32,
        "feiying_webhook_secret": "w" * 32,
        "admin_api_allowed_ips": "10.0.0.0/8",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_production_requires_admin_jwt_secret() -> None:
    settings = _production_settings(admin_jwt_secret="")

    with pytest.raises(RuntimeError, match="ADMIN_JWT_SECRET"):
        validate_runtime_security(settings)


def test_production_requires_admin_api_allowed_ips() -> None:
    settings = _production_settings(admin_api_allowed_ips="")

    with pytest.raises(RuntimeError, match="ADMIN_API_ALLOWED_IPS"):
        validate_runtime_security(settings)


def test_production_rejects_invalid_admin_api_allowed_ips_entry() -> None:
    settings = _production_settings(admin_api_allowed_ips="not-an-ip")

    with pytest.raises(RuntimeError, match="无效条目"):
        validate_runtime_security(settings)


def test_production_rejects_im_until_compliance_go() -> None:
    settings = Settings(
        app_env="prod",
        app_secret="production-app-secret",
        config_encryption_key="provider-config-key",
        activation_secret="activation-key",
        publish_session_encryption_key="publish-session-key",
        feiying_webhook_secret="webhook-secret",
        im_enabled=True,
    )

    with pytest.raises(RuntimeError, match="第三阶段合规结论为 No-Go"):
        validate_runtime_security(settings)


def test_enabled_im_requires_real_provider_key_even_in_test() -> None:
    settings = Settings(app_env="test", im_enabled=True, douyin_im_app_key="")

    with pytest.raises(RuntimeError, match="DOUYIN_IM_APP_KEY"):
        validate_runtime_security(settings)
