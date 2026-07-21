"""S3-05 IM message idempotency and ownership boundaries."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.im import repository as im_repo
from app.modules.im import service
from app.modules.im.models import IMConversation, IMMessage
from app.modules.publish import repository as publish_repo


async def _create_user() -> str:
    user_id = uuid.uuid4().hex
    async with SessionLocal() as db:
        db.add(
            User(
                id=user_id,
                phone=f"135{uuid.uuid4().hex[:8]}",
                password_hash=hash_password("Test@12345"),
                nickname="幂等测试",
                role="user",
            )
        )
        await db.commit()
    return user_id


async def _create_account(user_id: str) -> str:
    async with SessionLocal() as db:
        account = await publish_repo.create_account(
            db,
            user_id=user_id,
            platform="douyin",
            nickname="幂等账号",
            session_json='{"cookie_str":"sessionid=test"}',
        )
        await im_repo.approve_gray_account(db, account.id, approved_by="admin-test")
    return account.id


async def test_duplicate_remote_message_is_persisted_and_replied_once(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    del client
    user_id = await _create_user()
    account_id = await _create_account(user_id)
    emitted: list[dict] = []
    replies: list[str] = []

    async def capture_emit(_channel: str, payload: dict) -> None:
        emitted.append(payload)

    async def capture_reply(_db, _conversation: IMConversation, text: str) -> None:
        replies.append(text)

    monkeypatch.setattr(service, "emit", capture_emit)
    monkeypatch.setattr(service, "_try_auto_reply", capture_reply)

    async def deliver() -> None:
        await service.handle_incoming_message(
            account_id=account_id,
            user_id=user_id,
            remote_uid="remote-user",
            remote_nickname="远端用户",
            remote_avatar="",
            msg_type=7,
            content="价格是多少",
            dy_conversation_id="conversation-1",
            dy_conversation_short_id="1001",
            dy_ticket="ticket-1",
            remote_message_id="message-100",
            remote_index=7,
        )

    await deliver()
    await deliver()

    async with SessionLocal() as db:
        conversation = (
            await db.execute(
                select(IMConversation).where(
                    IMConversation.account_id == account_id,
                    IMConversation.user_id == user_id,
                )
            )
        ).scalar_one()
        message_count = (
            await db.execute(select(func.count()).where(IMMessage.conversation_id == conversation.id))
        ).scalar_one()
        message = (
            await db.execute(select(IMMessage).where(IMMessage.conversation_id == conversation.id))
        ).scalar_one()

    assert message_count == 1
    assert message.remote_message_id == "message-100"
    assert message.remote_index == 7
    assert conversation.unread_count == 1
    assert len(emitted) == 1
    assert replies == ["价格是多少"]


async def test_worker_cannot_persist_message_under_wrong_user(client: AsyncClient) -> None:
    del client
    owner_id = await _create_user()
    attacker_id = await _create_user()
    account_id = await _create_account(owner_id)

    await service.handle_incoming_message(
        account_id=account_id,
        user_id=attacker_id,
        remote_uid="remote-user",
        remote_nickname="",
        remote_avatar="",
        msg_type=7,
        content="越权消息",
        remote_message_id="message-attack",
        remote_index=1,
    )

    async with SessionLocal() as db:
        count = (
            await db.execute(select(func.count()).where(IMConversation.account_id == account_id))
        ).scalar_one()
    assert count == 0
