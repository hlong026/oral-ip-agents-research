"""S3-13 searchable, paginated, merged, and retained IM history."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.im import repository as im_repo
from app.modules.im import service as im_service
from app.modules.im.models import IMConversation, IMMessage
from app.modules.publish import repository as publish_repo


async def test_history_search_and_pagination_are_stable_and_user_scoped(client: AsyncClient) -> None:
    del client
    user_id = uuid.uuid4().hex
    other_user_id = uuid.uuid4().hex
    start = datetime(2026, 1, 1, tzinfo=UTC)
    primary = IMConversation(account_id="account-a", user_id=user_id, remote_uid="alice", remote_nickname="爱丽丝")
    matched = IMConversation(account_id="account-b", user_id=user_id, remote_uid="bob", remote_nickname="老客户")
    isolated = IMConversation(
        account_id="account-other",
        user_id=other_user_id,
        remote_uid="isolated",
        remote_nickname="隔离用户",
    )
    async with SessionLocal() as db:
        db.add_all([primary, matched, isolated])
        await db.flush()
        db.add_all(
            [
                IMMessage(
                    conversation_id=primary.id,
                    user_id=user_id,
                    content=f'{{"text":"订单-{index:03d}"}}',
                    created_at=start + timedelta(seconds=index),
                )
                for index in range(125)
            ]
            + [
                IMMessage(
                    conversation_id=matched.id,
                    user_id=user_id,
                    content='{"text":"请搜索特别线索"}',
                    created_at=start,
                ),
                IMMessage(
                    conversation_id=isolated.id,
                    user_id=other_user_id,
                    content='{"text":"特别线索不得跨用户出现"}',
                    created_at=start,
                ),
            ]
        )
        await db.commit()

        page = await im_service.list_messages(db, user_id, primary.id, page=3, page_size=50)
        message_match = await im_service.list_messages(
            db,
            user_id,
            primary.id,
            page=1,
            page_size=50,
            search="订单-042",
        )
        conversation_match = await im_service.list_conversations(
            db,
            user_id,
            page=1,
            page_size=20,
            search="特别线索",
        )
        account_match = await im_service.list_conversations(
            db,
            user_id,
            page=1,
            page_size=20,
            account_id="account-a",
        )

    assert page.total == 125 and len(page.items) == 25
    assert [item.content for item in page.items] == [f'{{"text":"订单-{index:03d}"}}' for index in range(24, -1, -1)]
    assert message_match.total == 1 and "订单-042" in message_match.items[0].content
    assert [item.id for item in conversation_match.items] == [matched.id]
    assert [item.id for item in account_match.items] == [primary.id]


async def test_incoming_messages_merge_conversation_and_refresh_remote_metadata(client: AsyncClient) -> None:
    del client
    user_id, account_id = await _create_account()
    await im_service.handle_incoming_message(
        account_id,
        user_id,
        "remote-merge",
        "旧昵称",
        "old-avatar",
        7,
        "第一条",
        dy_conversation_id="conversation-old",
        dy_conversation_short_id="100",
        dy_ticket="ticket-old",
        remote_message_id="message-1",
    )
    await im_service.handle_incoming_message(
        account_id,
        user_id,
        "remote-merge",
        "新昵称",
        "new-avatar",
        7,
        "第二条",
        dy_conversation_id="conversation-new",
        dy_conversation_short_id="200",
        dy_ticket="ticket-new",
        remote_message_id="message-2",
    )

    async with SessionLocal() as db:
        conversations = (
            await db.execute(
                select(IMConversation).where(
                    IMConversation.account_id == account_id,
                    IMConversation.user_id == user_id,
                    IMConversation.remote_uid == "remote-merge",
                )
            )
        ).scalars().all()
        message_count = (
            await db.execute(select(func.count(IMMessage.id)).where(IMMessage.conversation_id == conversations[0].id))
        ).scalar_one()

    assert len(conversations) == 1 and message_count == 2
    assert conversations[0].remote_nickname == "新昵称"
    assert conversations[0].remote_avatar == "new-avatar"
    assert conversations[0].dy_conversation_id == "conversation-new"
    assert conversations[0].dy_conversation_short_id == "200"
    assert conversations[0].dy_ticket == "ticket-new"


async def test_conversation_identity_has_database_uniqueness(client: AsyncClient) -> None:
    del client
    first = IMConversation(account_id="unique-account", user_id="unique-user", remote_uid="unique-remote")
    duplicate = IMConversation(account_id="unique-account", user_id="unique-user", remote_uid="unique-remote")
    async with SessionLocal() as db:
        db.add(first)
        await db.commit()
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


async def test_history_cleanup_is_batched_and_preserves_actionable_messages(client: AsyncClient) -> None:
    del client
    user_id = uuid.uuid4().hex
    cutoff = datetime(2025, 1, 1, tzinfo=UTC)
    old_conversation = IMConversation(
        account_id="account-old",
        user_id=user_id,
        remote_uid="old",
        last_message_at=cutoff - timedelta(days=1),
    )
    protected_conversation = IMConversation(
        account_id="account-protected",
        user_id=user_id,
        remote_uid="protected",
        last_message_at=cutoff - timedelta(days=1),
    )
    recent_conversation = IMConversation(
        account_id="account-recent",
        user_id=user_id,
        remote_uid="recent",
        last_message_at=cutoff + timedelta(days=1),
    )
    async with SessionLocal() as db:
        db.add_all([old_conversation, protected_conversation, recent_conversation])
        await db.flush()
        old_message = IMMessage(
            conversation_id=old_conversation.id,
            user_id=user_id,
            content='{"text":"应清理"}',
            send_status="sent",
            created_at=cutoff - timedelta(days=2),
        )
        protected_message = IMMessage(
            conversation_id=protected_conversation.id,
            user_id=user_id,
            content='{"text":"排队消息必须保留"}',
            send_status="scheduled",
            created_at=cutoff - timedelta(days=2),
        )
        recent_message = IMMessage(
            conversation_id=recent_conversation.id,
            user_id=user_id,
            content='{"text":"近期消息"}',
            send_status="sent",
            created_at=cutoff + timedelta(days=1),
        )
        db.add_all([old_message, protected_message, recent_message])
        await db.commit()

        deleted_messages, deleted_conversations = await im_repo.cleanup_history(
            db,
            cutoff=cutoff,
            batch_size=1,
            max_batches=10,
        )
        loaded_old = await im_repo.get_message_by_id(db, old_message.id)
        loaded_protected = await im_repo.get_message_by_id(db, protected_message.id)
        loaded_recent = await im_repo.get_message_by_id(db, recent_message.id)
        loaded_old_conversation = await im_repo.get_conversation(db, old_conversation.id, user_id)

    assert (deleted_messages, deleted_conversations) == (1, 1)
    assert loaded_old is None and loaded_old_conversation is None
    assert loaded_protected is not None
    assert loaded_recent is not None


async def _create_account() -> tuple[str, str]:
    user_id = uuid.uuid4().hex
    async with SessionLocal() as db:
        db.add(
            User(
                id=user_id,
                phone=f"131{uuid.uuid4().hex[:8]}",
                password_hash=hash_password("Test@12345"),
                nickname="历史消息测试",
                role="user",
            )
        )
        await db.commit()
        account = await publish_repo.create_account(
            db,
            user_id=user_id,
            platform="douyin",
            nickname="历史账号",
            session_json='{"cookie_str":"sessionid=test"}',
        )
        await im_repo.approve_gray_account(db, account.id, approved_by="admin-test")
    return user_id, account.id
