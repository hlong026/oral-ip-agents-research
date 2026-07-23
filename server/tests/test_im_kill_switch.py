"""S3-11 explicit automation consent and emergency kill switches."""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import create_access_token, hash_password
from app.modules.auth.models import User
from app.modules.im import repository as im_repo
from app.modules.im import service
from app.modules.im.models import IMAutoReplyRule, IMConversation, IMMessage
from app.modules.im.schemas import AutomationConsentIn
from app.modules.publish import repository as publish_repo


async def test_auto_mode_without_consent_remains_a_suggestion(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    del client
    user_id, account_id = await _create_user_account()
    conversation, _rule = await _create_auto_rule(user_id, account_id)
    monkeypatch.setattr(service, "_get_reply_limiter", lambda: _AllowLimiter())
    monkeypatch.setattr(
        service,
        "_schedule_auto_reply",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unauthorized auto reply must not queue")),
    )

    async with SessionLocal() as db:
        await service._try_auto_reply(db, conversation, "你好")
        message = (await db.execute(select(IMMessage).where(IMMessage.conversation_id == conversation.id))).scalar_one()

    assert message.send_status == "suggested"
    assert message.send_error == "AutomationNotAuthorized"


async def test_authorized_account_can_queue_only_when_global_switch_is_open(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    del client
    user_id, account_id = await _create_user_account()
    conversation, _rule = await _create_auto_rule(user_id, account_id)
    monkeypatch.setattr(service, "_get_reply_limiter", lambda: _AllowLimiter())
    monkeypatch.setattr(service, "_schedule_auto_reply", lambda _message_id, _delay: "queue-1")

    async with SessionLocal() as db:
        await service.authorize_automation(
            db,
            user_id,
            AutomationConsentIn(accountId=account_id, accepted=True, riskVersion="im-auto-reply-v1"),
        )
        await service.set_global_kill_switch(db, stopped=False)
        await service._try_auto_reply(db, conversation, "你好")
        message = (await db.execute(select(IMMessage).where(IMMessage.conversation_id == conversation.id))).scalar_one()

    assert message.send_status == "scheduled"
    assert message.queue_message_id == "queue-1"


async def test_global_kill_switch_cancels_queued_messages_before_provider_call(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    del client
    user_id, account_id = await _create_user_account()
    conversation, _rule = await _create_auto_rule(user_id, account_id)
    async with SessionLocal() as db:
        await service.authorize_automation(
            db,
            user_id,
            AutomationConsentIn(accountId=account_id, accepted=True, riskVersion="im-auto-reply-v1"),
        )
        await service.set_global_kill_switch(db, stopped=False)
        queued = await im_repo.create_message(
            db,
            conversation_id=conversation.id,
            user_id=user_id,
            direction="out",
            msg_type=7,
            content='{"text":"待发送"}',
            auto_replied=True,
            send_status="scheduled",
        )
        canceled = await service.set_global_kill_switch(db, stopped=True)

    monkeypatch.setattr(
        service.registry,
        "im_driver",
        lambda _platform: (_ for _ in ()).throw(AssertionError("kill switch must stop provider")),
    )
    await service.run_scheduled_reply(queued.id)

    async with SessionLocal() as db:
        message = await im_repo.get_message_by_id(db, queued.id)
    assert canceled >= 1
    assert message is not None
    assert message.send_status == "canceled"


async def test_user_cannot_authorize_another_users_account(client: AsyncClient) -> None:
    del client
    owner_id, account_id = await _create_user_account()
    attacker_id, _ = await _create_user_account()

    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as error:
            await service.authorize_automation(
                db,
                attacker_id,
                AutomationConsentIn(accountId=account_id, accepted=True, riskVersion="im-auto-reply-v1"),
            )

    assert owner_id != attacker_id
    assert error.value.status_code == 404


async def test_account_kill_switch_cancels_only_owned_account_queue(client: AsyncClient) -> None:
    del client
    user_id, account_id = await _create_user_account()
    conversation, _rule = await _create_auto_rule(user_id, account_id)
    other_user_id, other_account_id = await _create_user_account()
    other_conversation, _other_rule = await _create_auto_rule(other_user_id, other_account_id)

    async with SessionLocal() as db:
        await service.authorize_automation(
            db,
            user_id,
            AutomationConsentIn(accountId=account_id, accepted=True, riskVersion="im-auto-reply-v1"),
        )
        own_message = await im_repo.create_message(
            db,
            conversation_id=conversation.id,
            user_id=user_id,
            direction="out",
            msg_type=7,
            content='{"text":"本账号待发送"}',
            send_status="scheduled",
        )
        other_message = await im_repo.create_message(
            db,
            conversation_id=other_conversation.id,
            user_id=other_user_id,
            direction="out",
            msg_type=7,
            content='{"text":"其他账号待发送"}',
            send_status="scheduled",
        )
        status_out = await service.disable_automation(db, user_id, account_id)
        loaded_own_message = await im_repo.get_message_by_id(db, own_message.id)
        loaded_other_message = await im_repo.get_message_by_id(db, other_message.id)

    assert status_out.authorized is False
    assert loaded_own_message is not None and loaded_own_message.send_status == "canceled"
    assert loaded_other_message is not None and loaded_other_message.send_status == "scheduled"


async def test_global_kill_switch_requires_admin_audience(client: AsyncClient) -> None:
    user_id = await _create_user(role="user")
    admin_id = await _create_user(role="admin")
    user_response = await client.put(
        "/api/admin/v1/im/kill-switch",
        headers={"Authorization": f"Bearer {create_access_token(user_id)}"},
        json={"stopped": True},
    )
    admin_response = await client.put(
        "/api/admin/v1/im/kill-switch",
        headers={"Authorization": f"Bearer {create_access_token(admin_id, audience='admin')}"},
        json={"stopped": True},
    )

    assert user_response.status_code == 403
    assert admin_response.status_code == 200
    assert admin_response.json()["stopped"] is True


async def _create_user_account() -> tuple[str, str]:
    user_id = await _create_user(role="user")
    async with SessionLocal() as db:
        account = await publish_repo.create_account(
            db,
            user_id=user_id,
            platform="douyin",
            nickname="授权账号",
            session_json='{"cookie_str":"sessionid=test"}',
        )
        await im_repo.approve_gray_account(db, account.id, approved_by="admin-test")
    return user_id, account.id


async def _create_user(*, role: str) -> str:
    user_id = uuid.uuid4().hex
    async with SessionLocal() as db:
        db.add(
            User(
                id=user_id,
                phone=f"133{uuid.uuid4().hex[:8]}",
                password_hash=hash_password("Test@12345"),
                nickname="授权测试",
                role=role,
                activated_at=datetime.now(UTC),
            )
        )
        await db.commit()
    return user_id


async def _create_auto_rule(user_id: str, account_id: str) -> tuple[IMConversation, IMAutoReplyRule]:
    conversation = IMConversation(account_id=account_id, user_id=user_id, remote_uid=uuid.uuid4().hex)
    rule = IMAutoReplyRule(
        user_id=user_id,
        account_id=account_id,
        trigger_type="all",
        reply_mode="template",
        reply_template="安全回复",
        delivery_mode="auto",
        enabled=True,
    )
    async with SessionLocal() as db:
        db.add_all([conversation, rule])
        await db.commit()
        await db.refresh(conversation)
    return conversation, rule


class _AllowLimiter:
    async def reserve(self, **_kwargs: object) -> bool:
        return True
