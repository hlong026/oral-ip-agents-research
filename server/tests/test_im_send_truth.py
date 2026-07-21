"""S3-06 truthful IM send state, retry, and manual takeover."""

import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.im import repository as im_repo
from app.modules.im import service
from app.modules.im.models import IMConversation, IMMessage
from app.modules.im.schemas import SendMessageIn
from app.modules.publish import repository as publish_repo


async def _create_conversation() -> tuple[str, IMConversation]:
    user_id = uuid.uuid4().hex
    async with SessionLocal() as db:
        db.add(
            User(
                id=user_id,
                phone=f"134{uuid.uuid4().hex[:8]}",
                password_hash=hash_password("Test@12345"),
                nickname="发送测试",
                role="user",
            )
        )
        await db.commit()
        account = await publish_repo.create_account(
            db,
            user_id=user_id,
            platform="douyin",
            nickname="发送账号",
            session_json='{"cookie_str":"sessionid=test"}',
        )
        await im_repo.approve_gray_account(db, account.id, approved_by="admin-test")
        conversation = IMConversation(
            account_id=account.id,
            user_id=user_id,
            platform="douyin",
            remote_uid="remote-user",
            dy_conversation_id="conversation-1",
            dy_conversation_short_id="1001",
            dy_ticket="ticket-1",
        )
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)
    return user_id, conversation


async def test_provider_false_records_failed_message_not_success(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    del client
    user_id, conversation = await _create_conversation()
    provider = _Provider([False])
    monkeypatch.setattr(service.registry, "im_driver", lambda _platform: provider)
    monkeypatch.setattr(service, "_load_account_session", _fake_session)

    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as error:
            await service.send_message(db, user_id, conversation.id, SendMessageIn(content="发送失败"))

    assert error.value.status_code == 502
    async with SessionLocal() as db:
        result = await db.execute(select(IMMessage).where(IMMessage.conversation_id == conversation.id))
        messages = list(result.scalars())
    assert len(messages) == 1
    assert messages[0].send_status == "failed"
    assert messages[0].send_error
    assert all(message.send_status != "sent" for message in messages)


async def test_failed_message_can_retry_then_switch_to_manual_takeover(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    del client
    user_id, conversation = await _create_conversation()
    provider = _Provider([False, True, False])
    monkeypatch.setattr(service.registry, "im_driver", lambda _platform: provider)
    monkeypatch.setattr(service, "_load_account_session", _fake_session)

    async with SessionLocal() as db:
        with pytest.raises(HTTPException):
            await service.send_message(db, user_id, conversation.id, SendMessageIn(content="请重试"))
        message = (await db.execute(select(IMMessage).where(IMMessage.conversation_id == conversation.id))).scalar_one()
        retried = await service.retry_message(db, user_id, message.id)

    assert retried.sendStatus == "sent"
    assert retried.retryCount == 1

    async with SessionLocal() as db:
        with pytest.raises(HTTPException):
            await service.send_message(db, user_id, conversation.id, SendMessageIn(content="人工处理"))
        failed = (
            await db.execute(
                select(IMMessage).where(
                    IMMessage.conversation_id == conversation.id,
                    IMMessage.send_status == "failed",
                )
            )
        ).scalar_one()
        taken_over = await service.take_over_message(db, user_id, failed.id)
        with pytest.raises(HTTPException) as error:
            await service.retry_message(db, user_id, failed.id)

    assert taken_over.sendStatus == "manual"
    assert taken_over.manualTakeover is True
    assert error.value.status_code == 409


async def test_auto_reply_failure_is_also_persisted(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    del client
    user_id, conversation = await _create_conversation()
    monkeypatch.setattr(service.registry, "im_driver", lambda _platform: _Provider([False]))
    monkeypatch.setattr(service, "_load_account_session", _fake_session)
    monkeypatch.setattr(service.repo, "automation_block_reason", AsyncMock(return_value=None))

    async with SessionLocal() as db:
        queued = await service.repo.create_message(
            db,
            conversation_id=conversation.id,
            user_id=user_id,
            direction="out",
            msg_type=7,
            content='{"text":"自动回复失败"}',
            auto_replied=True,
            rule_id="rule-1",
            send_status="scheduled",
        )

    await service.run_scheduled_reply(queued.id)

    async with SessionLocal() as db:
        message = (await db.execute(select(IMMessage).where(IMMessage.conversation_id == conversation.id))).scalar_one()
    assert message.auto_replied is True
    assert message.send_status == "failed"
    assert message.send_error


async def test_duplicate_scheduled_delivery_calls_provider_once(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del client
    user_id, conversation = await _create_conversation()
    async with SessionLocal() as db:
        message = await im_repo.create_message(
            db,
            conversation_id=conversation.id,
            user_id=user_id,
            direction="out",
            msg_type=7,
            content='{"text":"只能发送一次"}',
            auto_replied=True,
            send_status="scheduled",
        )

    provider = _CountingProvider()
    original_get = service.repo.get_message_by_id
    both_loaded = asyncio.Event()
    load_count = 0

    async def load_with_barrier(db, message_id: str):
        nonlocal load_count
        loaded = await original_get(db, message_id)
        load_count += 1
        if load_count == 2:
            both_loaded.set()
        await both_loaded.wait()
        return loaded

    monkeypatch.setattr(service.repo, "get_message_by_id", load_with_barrier)
    monkeypatch.setattr(service.repo, "automation_block_reason", AsyncMock(return_value=None))
    monkeypatch.setattr(service.registry, "im_driver", lambda _platform: provider)
    monkeypatch.setattr(service, "_load_account_session", _fake_session)
    monkeypatch.setattr(service, "emit", _ignore_emit)

    await asyncio.gather(
        service.run_scheduled_reply(message.id),
        service.run_scheduled_reply(message.id),
    )

    assert provider.calls == 1


async def test_concurrent_retry_claims_failed_message_once(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del client
    user_id, conversation = await _create_conversation()
    async with SessionLocal() as db:
        message = await im_repo.create_message(
            db,
            conversation_id=conversation.id,
            user_id=user_id,
            direction="out",
            msg_type=7,
            content='{"text":"只重试一次"}',
            send_status="failed",
        )

    provider = _CountingProvider()
    original_get = service.repo.get_message
    both_loaded = asyncio.Event()
    load_count = 0

    async def load_with_barrier(db, message_id: str, owner_id: str):
        nonlocal load_count
        loaded = await original_get(db, message_id, owner_id)
        load_count += 1
        if load_count == 2:
            both_loaded.set()
        await both_loaded.wait()
        return loaded

    monkeypatch.setattr(service.repo, "get_message", load_with_barrier)
    monkeypatch.setattr(service.registry, "im_driver", lambda _platform: provider)
    monkeypatch.setattr(service, "_load_account_session", _fake_session)

    async with SessionLocal() as first_db, SessionLocal() as second_db:
        results = await asyncio.gather(
            service.retry_message(first_db, user_id, message.id),
            service.retry_message(second_db, user_id, message.id),
            return_exceptions=True,
        )

    assert provider.calls == 1
    assert sum(isinstance(result, HTTPException) and result.status_code == 409 for result in results) == 1


class _Provider:
    def __init__(self, results: list[bool]):
        self._results = iter(results)

    async def send_message(self, **_kwargs: object) -> bool:
        return next(self._results)


class _CountingProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def send_message(self, **_kwargs: object) -> bool:
        self.calls += 1
        return True


async def _fake_session(_account_id: str, _user_id: str) -> dict[str, str]:
    return {"cookie_str": "sessionid=test"}


async def _ignore_emit(_channel: str, _payload: dict) -> None:
    return None
