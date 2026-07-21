"""私信业务层不得展示或保存伪造的真实业务数据。"""

import json

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
