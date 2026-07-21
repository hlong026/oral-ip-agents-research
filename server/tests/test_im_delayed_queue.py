"""S3-09 durable delayed IM auto replies."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.im import repository as im_repo
from app.modules.im import service
from app.modules.im.models import IMAutoReplyRule, IMConversation, IMMessage


async def test_auto_reply_is_persisted_before_dramatiq_delay(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    del client
    user_id = uuid.uuid4().hex
    conversation = IMConversation(account_id="account-queue", user_id=user_id, remote_uid="remote-queue")
    rule = IMAutoReplyRule(
        user_id=user_id,
        account_id=conversation.account_id,
        trigger_type="all",
        reply_mode="template",
        reply_template="排队回复",
        delay_min=3,
        delay_max=3,
        delivery_mode="auto",
        enabled=True,
    )
    async with SessionLocal() as db:
        db.add_all([conversation, rule])
        await db.commit()
        await db.refresh(conversation)

        monkeypatch.setattr(service, "_get_reply_limiter", lambda: _AllowLimiter())
        monkeypatch.setattr(service.repo, "automation_block_reason", AsyncMock(return_value=None))
        scheduled: list[tuple[str, int]] = []

        def capture_schedule(message_id: str, delay_ms: int) -> str:
            scheduled.append((message_id, delay_ms))
            return "queue-message-1"

        monkeypatch.setattr(
            service,
            "_schedule_auto_reply",
            capture_schedule,
        )

        await service._try_auto_reply(db, conversation, "你好")

        message = (
            await db.execute(select(IMMessage).where(IMMessage.conversation_id == conversation.id))
        ).scalar_one()

    assert message.send_status == "scheduled"
    assert message.queue_message_id == "queue-message-1"
    assert message.scheduled_at is not None
    assert scheduled == [(message.id, 3000)]


async def test_scheduled_reply_can_resume_from_message_id_after_restart(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    del client
    user_id = uuid.uuid4().hex
    conversation = IMConversation(
        account_id="account-resume",
        user_id=user_id,
        remote_uid="remote-resume",
        dy_conversation_id="conversation-1",
        dy_conversation_short_id="1001",
        dy_ticket="ticket-1",
    )
    async with SessionLocal() as db:
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)
        message = await im_repo.create_message(
            db,
            conversation_id=conversation.id,
            user_id=user_id,
            direction="out",
            msg_type=7,
            content='{"text":"重启后继续"}',
            auto_replied=True,
            send_status="scheduled",
            queue_message_id="queue-message-2",
        )

    monkeypatch.setattr(service.registry, "im_driver", lambda _platform: _Provider())
    monkeypatch.setattr(service.repo, "automation_block_reason", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "_load_account_session", _fake_session)
    monkeypatch.setattr(service, "emit", _ignore_emit)

    await service.run_scheduled_reply(message.id)

    async with SessionLocal() as db:
        resumed = await im_repo.get_message_by_id(db, message.id)
    assert resumed is not None
    assert resumed.send_status == "sent"


def test_dramatiq_delay_uses_persisted_message_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workers import tasks

    captured: dict[str, object] = {}

    def fake_send_with_options(*, args: tuple[str], delay: int) -> SimpleNamespace:
        captured.update(args=args, delay=delay)
        return SimpleNamespace(message_id="dramatiq-message")

    monkeypatch.setattr(tasks.run_im_auto_reply, "send_with_options", fake_send_with_options)

    queue_id = service._schedule_auto_reply("message-1", 4500)

    assert queue_id == "dramatiq-message"
    assert captured == {"args": ("message-1",), "delay": 4500}


class _AllowLimiter:
    async def reserve(self, **_kwargs: object) -> bool:
        return True


class _Provider:
    async def send_message(self, **_kwargs: object) -> bool:
        return True


async def _fake_session(_account_id: str, _user_id: str) -> dict[str, str]:
    return {"cookie_str": "sessionid=test"}


async def _ignore_emit(_channel: str, _payload: dict) -> None:
    return None
