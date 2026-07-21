"""JWT behavior must remain stable across security-library changes."""

from app.core import security


def test_access_token_round_trip_and_type_guard() -> None:
    token = security.create_access_token("user-1", device_id="device-1")

    payload = security.decode_token(token)

    assert payload is not None
    assert payload["sub"] == "user-1"
    assert payload["dev"] == "device-1"
    assert payload["type"] == "access"
    assert security.decode_token(token, expected_type="refresh") is None


def test_expired_or_tampered_token_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(security.settings, "access_token_ttl_min", -1)
    expired = security.create_access_token("user-1")

    assert security.decode_token(expired) is None
    assert security.decode_token(f"{expired}tampered") is None
