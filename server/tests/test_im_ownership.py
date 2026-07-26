"""IM account ownership boundaries."""

import uuid

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.core.db import SessionLocal
from app.modules.auth.models import User
from app.modules.im.models import IMListenerState
from app.modules.publish import repository as publish_repo
from tests.helpers import bind_used_code, code_login


async def _create_user_and_login(client: AsyncClient) -> tuple[str, dict[str, str]]:
    user_id = uuid.uuid4().hex
    async with SessionLocal() as db:
        db.add(
            User(
                id=user_id,
                nickname="归属测试",
                role="user",
            )
        )
        await db.commit()
    code = await bind_used_code(user_id)
    fingerprint = f"fp-{uuid.uuid4().hex[:12]}.abcd1234"
    tokens = await code_login(client, code, fingerprint=fingerprint)
    return user_id, {"Authorization": f"Bearer {tokens['accessToken']}"}


async def _create_publish_account(user_id: str) -> str:
    async with SessionLocal() as db:
        account = await publish_repo.create_account(
            db,
            user_id=user_id,
            platform="douyin",
            nickname="被保护账号",
            session_json='{"cookie_str":"secret-cookie"}',
        )
        return account.id


async def test_user_cannot_start_or_stop_another_users_listener(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    attacker_id, _ = await _create_user_and_login(client)
    owner_id, _ = await _create_user_and_login(client)
    account_id = await _create_publish_account(owner_id)

    from app.workers import im_listener

    monkeypatch.setattr(im_listener, "start_listening", lambda *_args: None)
    monkeypatch.setattr(im_listener, "stop_listening", lambda *_args: None)

    from app.modules.im import service
    from app.modules.im.schemas import ListenerControlIn

    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as start_error:
            await service.start_listener(db, attacker_id, ListenerControlIn(accountId=account_id))
        with pytest.raises(HTTPException) as stop_error:
            await service.stop_listener(db, attacker_id, ListenerControlIn(accountId=account_id))

    assert attacker_id != owner_id
    assert start_error.value.status_code == 404
    assert stop_error.value.status_code == 404


async def test_restore_skips_listener_state_that_does_not_own_account(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stale_user_id, _ = await _create_user_and_login(client)
    owner_id, _ = await _create_user_and_login(client)
    account_id = await _create_publish_account(owner_id)
    async with SessionLocal() as db:
        db.add(
            IMListenerState(
                account_id=account_id,
                user_id=stale_user_id,
                status="listening",
            )
        )
        await db.commit()

    from app.core.config import get_settings
    from app.workers import im_listener

    restored: list[tuple[str, str]] = []
    monkeypatch.setattr(get_settings(), "im_enabled", True)
    monkeypatch.setattr(im_listener, "start_listening", lambda account, user: restored.append((account, user)))

    await im_listener.restore_listeners()

    assert restored == []
