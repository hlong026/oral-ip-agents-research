"""私信业务层不得展示或保存伪造的真实业务数据。"""

import json
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.modules.im import repository as im_repo
from app.modules.im import service as im_service
from app.modules.im.models import IMMessage
from app.modules.im.schemas import ListenerControlIn, SendMessageIn
from app.modules.publish import repository as publish_repo
from app.providers.registry import registry


@pytest.mark.asyncio
async def test_conversation_list_excludes_persisted_mock_users(client) -> None:
    async with SessionLocal() as db:
        await im_repo.create_conversation(
            db,
            account_id="account-1",
            user_id="user-1",
            remote_uid="mock-user",
            remote_nickname="小明",
            dy_ticket="mock_ticket",
        )
        real = await im_repo.create_conversation(
            db,
            account_id="account-1",
            user_id="user-1",
            remote_uid="123456789",
            remote_nickname="",
            dy_ticket="",
        )

        items, total = await im_repo.list_conversations(db, "user-1")

    assert total == 1
    assert [item.id for item in items] == [real.id]


@pytest.mark.asyncio
async def test_failed_provider_send_is_not_saved_as_success(client, monkeypatch: pytest.MonkeyPatch) -> None:
    class FailedProvider:
        async def send_message(self, **kwargs) -> bool:
            return False

    async with SessionLocal() as db:
        account = await publish_repo.create_account(
            db,
            user_id="user-2",
            platform="douyin",
            nickname="真实账号",
            session_json=json.dumps({"cookie_str": "sessionid=session-value", "sessionid": "session-value"}),
        )
        conversation = await im_repo.create_conversation(
            db,
            account_id=account.id,
            user_id="user-2",
            remote_uid="987654321",
            dy_conversation_id="conversation-id",
        )
        monkeypatch.setattr(registry, "im_driver", lambda platform: FailedProvider())

        with pytest.raises(HTTPException) as exc_info:
            await im_service.send_message(db, "user-2", conversation.id, SendMessageIn(content="不会假成功"))

        count = (
            await db.execute(select(func.count(IMMessage.id)).where(IMMessage.conversation_id == conversation.id))
        ).scalar_one()

    assert exc_info.value.status_code == 502
    assert count == 0


@pytest.mark.asyncio
async def test_listener_rejects_account_without_im_device_id(client) -> None:
    async with SessionLocal() as db:
        account = await publish_repo.create_account(
            db,
            user_id="user-3",
            platform="douyin",
            nickname="旧登录态",
            session_json=json.dumps(
                {
                    "cookies": [{"name": "sessionid", "value": "session-value", "domain": ".douyin.com", "path": "/"}],
                    "origins": [],
                }
            ),
        )

        with pytest.raises(HTTPException) as exc_info:
            await im_service.start_listener(db, "user-3", ListenerControlIn(accountId=account.id))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "IM_SESSION_INCOMPLETE"


@pytest.mark.asyncio
async def test_incoming_message_is_idempotent_by_remote_message_id(client, monkeypatch: pytest.MonkeyPatch) -> None:
    auto_reply = AsyncMock()
    monkeypatch.setattr(im_service, "_try_auto_reply", auto_reply)

    payload = {
        "account_id": "account-dedupe",
        "user_id": "user-dedupe",
        "remote_uid": "123456789",
        "remote_nickname": "真实用户",
        "remote_avatar": "",
        "msg_type": 7,
        "content": "重复推送",
        "dy_conversation_id": "conversation-dedupe",
        "dy_conversation_short_id": "9988",
        "remote_message_id": "server-message-1",
        "remote_index": 7,
    }
    await im_service.handle_incoming_message(**payload)
    await im_service.handle_incoming_message(**payload)

    async with SessionLocal() as db:
        conversation = await im_repo.get_conversation_by_dy_id(db, "account-dedupe", "123456789")
        assert conversation is not None
        count = (
            await db.execute(select(func.count(IMMessage.id)).where(IMMessage.conversation_id == conversation.id))
        ).scalar_one()

    assert count == 1
    assert conversation.unread_count == 1
    auto_reply.assert_awaited_once()


@pytest.mark.asyncio
async def test_history_sync_imports_browser_messages_idempotently(client, monkeypatch: pytest.MonkeyPatch) -> None:
    class BrowserProvider:
        async def sync_messages(self, session: dict, limit: int) -> list[dict]:
            assert session["cookies"][0]["name"] == "sessionid"
            assert limit == 100
            return [
                {
                    "remote_uid": "browser:user-a",
                    "remote_nickname": "历史用户A",
                    "remote_avatar": "https://example.com/avatar.png",
                    "direction": "in",
                    "msg_type": 7,
                    "content": "历史消息",
                    "dy_conversation_id": "browser-conversation-a",
                    "dy_conversation_short_id": "",
                    "dy_ticket": "",
                    "remote_message_id": "browser-message-a",
                    "remote_index": 1,
                }
            ]

    async with SessionLocal() as db:
        account = await publish_repo.create_account(
            db,
            user_id="user-sync",
            platform="douyin",
            nickname="同步账号",
            session_json=json.dumps(
                {
                    "cookies": [{"name": "sessionid", "value": "session-value", "domain": ".douyin.com", "path": "/"}],
                    "origins": [],
                }
            ),
        )
        monkeypatch.setattr(registry, "im_driver", lambda platform: BrowserProvider())

        first = await im_service.sync_account_messages(db, "user-sync", account.id)
        second = await im_service.sync_account_messages(db, "user-sync", account.id)
        conversation = await im_repo.get_conversation_by_dy_id(db, account.id, "browser:user-a")
        assert conversation is not None
        count = (
            await db.execute(select(func.count(IMMessage.id)).where(IMMessage.conversation_id == conversation.id))
        ).scalar_one()

    assert first.imported == 1
    assert second.imported == 0
    assert count == 1
    assert conversation.unread_count == 0


@pytest.mark.asyncio
async def test_successful_browser_send_is_saved_after_confirmation(client, monkeypatch: pytest.MonkeyPatch) -> None:
    class SuccessfulProvider:
        def __init__(self) -> None:
            self.kwargs: dict = {}

        async def send_message(self, **kwargs) -> bool:
            self.kwargs = kwargs
            return True

        async def sync_messages(self, session: dict, limit: int) -> list[dict]:
            return [
                {
                    "remote_uid": "browser:user-b",
                    "remote_nickname": "回复对象",
                    "remote_avatar": "",
                    "direction": "out",
                    "msg_type": 7,
                    "content": "真实回复",
                    "dy_conversation_id": "browser-conversation-b",
                    "remote_message_id": "browser:sent-message-1",
                }
            ]

    provider = SuccessfulProvider()
    async with SessionLocal() as db:
        account = await publish_repo.create_account(
            db,
            user_id="user-send",
            platform="douyin",
            nickname="回复账号",
            session_json=json.dumps({"cookies": [{"name": "sessionid", "value": "session-value"}]}),
        )
        conversation = await im_repo.create_conversation(
            db,
            account_id=account.id,
            user_id="user-send",
            remote_uid="browser:user-b",
            remote_nickname="回复对象",
            dy_conversation_id="browser-conversation-b",
        )
        monkeypatch.setattr(registry, "im_driver", lambda platform: provider)

        result = await im_service.send_message(db, "user-send", conversation.id, SendMessageIn(content="真实回复"))
        sync_result = await im_service.sync_account_messages(db, "user-send", account.id)
        count = (
            await db.execute(select(func.count(IMMessage.id)).where(IMMessage.conversation_id == conversation.id))
        ).scalar_one()
        message = (await db.execute(select(IMMessage).where(IMMessage.conversation_id == conversation.id))).scalar_one()

    assert count == 1
    assert sync_result.imported == 0
    assert message.remote_message_id == "browser:sent-message-1"
    assert result.direction == "out"
    assert provider.kwargs["remote_uid"] == "browser:user-b"
    assert provider.kwargs["remote_nickname"] == "回复对象"
    assert provider.kwargs["content"] == "真实回复"
