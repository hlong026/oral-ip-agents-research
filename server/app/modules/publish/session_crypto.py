"""Encryption boundary for publish-account browser sessions."""

import base64
import hashlib
import json
import logging
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

logger = logging.getLogger("oral.publish.session_crypto")

_SESSION_PREFIX = "enc:publish-session:v1:"


def _fernet() -> Fernet:
    settings = get_settings()
    secret = settings.publish_session_encryption_key
    if not secret and settings.app_env not in {"dev", "test"}:
        raise RuntimeError("生产环境必须配置 PUBLISH_SESSION_ENCRYPTION_KEY")
    key_material = (secret or settings.app_secret).encode("utf-8")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key_material).digest()))


def is_encrypted_session(value: str) -> bool:
    return value.startswith(_SESSION_PREFIX)


def encrypt_session_value(value: str) -> str:
    if is_encrypted_session(value):
        return value
    plaintext = value or "{}"
    parsed = json.loads(plaintext)
    if not isinstance(parsed, dict):
        raise ValueError("发布会话必须是 JSON 对象")
    token = _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")
    return _SESSION_PREFIX + token


def decrypt_session_value(value: str) -> str:
    if not value:
        return "{}"
    if not is_encrypted_session(value):
        return value
    try:
        token = value.removeprefix(_SESSION_PREFIX).encode("utf-8")
        return _fernet().decrypt(token).decode("utf-8")
    except InvalidToken as exc:
        logger.error("publish_session_decrypt_failed")
        raise RuntimeError("发布账号凭据无法解密") from exc


def decode_session(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(decrypt_session_value(value))
    except json.JSONDecodeError as exc:
        logger.error("publish_session_json_invalid")
        raise RuntimeError("发布账号凭据格式无效") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("发布账号凭据格式无效")
    return parsed
