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
