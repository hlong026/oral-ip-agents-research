from app.core.config import get_settings


def test_test_suite_always_uses_isolated_local_storage() -> None:
    settings = get_settings()

    assert settings.app_env == "test"
    assert settings.storage_driver == "local"
    assert "oral-test-" in settings.local_storage_dir
