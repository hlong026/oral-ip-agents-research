"""Desktop WebView origins must remain available for local desktop login."""

from app.main import _cors_origins


def test_dev_cors_includes_tauri_desktop_origins() -> None:
    origins = _cors_origins("dev", "")

    assert "tauri://localhost" in origins
    assert "http://tauri.localhost" in origins
    assert "https://tauri.localhost" in origins


def test_staging_cors_keeps_only_explicit_origins() -> None:
    origins = _cors_origins("staging", "https://app.example.com,tauri://localhost")

    assert origins == ["https://app.example.com", "tauri://localhost"]
