from app.core.security import create_access_token, create_refresh_token, decode_token


def test_access_token_round_trip_preserves_claims():
    token = create_access_token("user-123", device_id="device-456", audience="admin")

    payload = decode_token(token)

    assert payload is not None
    assert payload["sub"] == "user-123"
    assert payload["type"] == "access"
    assert payload["dev"] == "device-456"
    assert payload["aud"] == "admin"
    assert payload["jti"]


def test_decode_token_rejects_wrong_type_and_malformed_token():
    refresh_token = create_refresh_token("user-123")

    assert decode_token(refresh_token) is None
    assert decode_token(refresh_token, expected_type="refresh") is not None
    assert decode_token("not-a-token") is None
