"""安全：密码散列 + JWT 双令牌（F-601 / C7）"""

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from jwt import InvalidTokenError

from .config import get_settings

settings = get_settings()


def hash_password(raw: str) -> str:
    # bcrypt 上限 72 字节，截断防 5.x 报错
    return bcrypt.hashpw(raw.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8")[:72], hashed.encode("utf-8"))
    except ValueError:
        return False


def consent_fingerprint(user_id: str, asset_kind: str, token: str) -> str:
    """保存可审计的授权指纹，不落授权凭证明文。"""
    message = f"{user_id}:{asset_kind}:{token.strip()}".encode()
    return hmac.new(settings.app_secret.encode(), message, hashlib.sha256).hexdigest()


def _make_token(
    subject: str,
    ttl: timedelta,
    token_type: str,
    device_id: str | None = None,
    audience: str = "user",
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": uuid.uuid4().hex,
        "aud": audience,
    }
    if device_id:
        payload["dev"] = device_id
    return jwt.encode(payload, settings.app_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: str, device_id: str | None = None, audience: str = "user") -> str:
    return _make_token(user_id, timedelta(minutes=settings.access_token_ttl_min), "access", device_id, audience)


def create_refresh_token(user_id: str, device_id: str | None = None, audience: str = "user") -> str:
    return _make_token(user_id, timedelta(days=settings.refresh_token_ttl_days), "refresh", device_id, audience)


def decode_token(token: str, expected_type: str = "access") -> dict | None:
    try:
        payload = jwt.decode(
            token,
            settings.app_secret,
            algorithms=[settings.jwt_algorithm],
            options={"verify_aud": False},
        )
    except InvalidTokenError:
        return None
    if payload.get("type") != expected_type:
        return None
    return payload
