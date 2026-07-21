"""Publish credential storage and temporary-file security."""

import json
import stat
import uuid

from app.core.db import SessionLocal
from app.modules.publish.models import PublishAccount


async def test_plaintext_publish_sessions_are_migrated_to_encrypted_storage(client) -> None:
    from app.modules.publish.repository import migrate_plaintext_sessions
    from app.modules.publish.session_crypto import decrypt_session_value, is_encrypted_session

    raw_session = json.dumps({"cookies": [{"name": "sessionid", "value": "secret-cookie"}]})
    account_id = uuid.uuid4().hex
    async with SessionLocal() as db:
        db.add(
            PublishAccount(
                id=account_id,
                user_id=uuid.uuid4().hex,
                platform="douyin",
                nickname="旧账号",
                session_json=raw_session,
            )
        )
        await db.commit()

        migrated = await migrate_plaintext_sessions(db)
        account = await db.get(PublishAccount, account_id)

    assert migrated >= 1
    assert account is not None
    assert is_encrypted_session(account.session_json)
    assert decrypt_session_value(account.session_json) == raw_session
    assert "secret-cookie" not in account.session_json


def test_cookie_temp_file_is_private_and_removed(tmp_path, monkeypatch) -> None:
    from app.providers.publish import cookie_manager

    monkeypatch.setattr(cookie_manager, "_COOKIE_DIR", tmp_path)
    cookie_path = cookie_manager.session_to_file(
        json.dumps({"cookies": [{"name": "sessionid", "value": "secret-cookie"}]}),
        "account-test",
        "douyin",
    )

    assert stat.S_IMODE(cookie_manager.Path(cookie_path).stat().st_mode) == 0o600
    assert "secret-cookie" in cookie_manager.Path(cookie_path).read_text(encoding="utf-8")

    cookie_manager.cleanup_cookie_file("account-test", "douyin")
    assert not cookie_manager.Path(cookie_path).exists()
