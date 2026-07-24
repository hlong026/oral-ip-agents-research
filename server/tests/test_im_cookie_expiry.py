"""S3-12 cookie expiry stops IM work and guides account reauthorization."""

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.im import repository as im_repo
from app.modules.im import service as im_service
from app.modules.im.models import IMConversation, IMListenerState
from app.modules.im.schemas import AutomationConsentIn
from app.modules.notify.models import Notification
from app.modules.publish import repository as publish_repo
from app.workers import im_listener


async def test_cookie_expiry_stops_listener_queue_and_automation_and_notifies_user(client: AsyncClient) -> None:
    del client
    user_id, account_id = await _create_account()
    conversation = IMConversation(account_id=account_id, user_id=user_id, remote_uid="expired-contact")
    async with SessionLocal() as db:
        db.add_all(
            [
                conversation,
                IMListenerState(account_id=account_id, user_id=user_id, status="listening"),
            ]
        )
        await db.commit()
        await db.refresh(conversation)
        await im_service.authorize_automation(
            db,
            user_id,
            AutomationConsentIn(accountId=account_id, accepted=True, riskVersion="im-auto-reply-v1"),
        )
        queued = await im_repo.create_message(
            db,
            conversation_id=conversation.id,
            user_id=user_id,
            direction="out",
            msg_type=7,
            content='{"text":"凭证失效后不得发送"}',
            auto_replied=True,
            send_status="scheduled",
        )

    await im_listener._mark_cookie_expired(account_id, user_id)

    async with SessionLocal() as db:
        account = await publish_repo.get_account(db, account_id, user_id)
        state = await im_repo.get_listener_state(db, account_id, user_id)
        consent = await im_repo.get_automation_consent(db, account_id, user_id)
        message = await im_repo.get_message_by_id(db, queued.id)
        notification = (await db.execute(select(Notification).where(Notification.user_id == user_id))).scalar_one()

    assert account is not None and account.status == "expired"
    assert state is not None and state.status == "error" and state.error_msg == "cookie_expired"
    assert consent is not None and consent.auto_reply_enabled is False
    assert message is not None and message.send_status == "canceled"
    assert message.send_error == "CredentialExpired"
    assert "重新授权" in notification.title + notification.body


async def test_listener_does_not_reconnect_after_cookie_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _BlockingConnection()
    lease = _FakeLease()
    provider = _CountingProvider(connection)

    monkeypatch.setattr(
        im_listener,
        "_load_account_context",
        AsyncMock(return_value=({"cookie_str": "expired"}, "douyin")),
    )
    monkeypatch.setattr(im_listener, "_listener_intent_active", AsyncMock(return_value=True))
    monkeypatch.setattr(im_listener, "_check_cookie_validity", AsyncMock(return_value=False))
    mark_expired = AsyncMock()
    monkeypatch.setattr(im_listener, "_mark_cookie_expired", mark_expired)
    monkeypatch.setattr(im_listener, "HEARTBEAT_INTERVAL", 0)
    monkeypatch.setattr(im_listener, "STATE_POLL_INTERVAL", 0.001)

    from app.providers.registry import registry

    monkeypatch.setattr(registry, "im_driver", lambda _platform: provider)
    await asyncio.wait_for(im_listener._listen_loop("account-expired", "user-expired", lease), timeout=1)

    assert provider.connect_calls == 1
    mark_expired.assert_awaited_once_with("account-expired", "user-expired")
    assert connection.closed is True
    assert lease.released is True


async def test_cookie_probe_network_error_is_not_treated_as_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    class UnavailableClient:
        async def __aenter__(self) -> "UnavailableClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def get(self, *_args: object, **_kwargs: object) -> object:
            raise httpx.ConnectError("temporary network failure")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: UnavailableClient())

    assert await im_listener._check_cookie_validity({"cookie_str": "sessionid=still-unknown"}) is None


async def test_expired_account_cannot_retry_failed_message(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    del client
    user_id, account_id = await _create_account()
    conversation = IMConversation(account_id=account_id, user_id=user_id, remote_uid="retry-contact")
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
            content='{"text":"不得重试"}',
            send_status="failed",
        )

    await im_listener._mark_cookie_expired(account_id, user_id)
    monkeypatch.setattr(
        im_service.registry,
        "im_driver",
        lambda _platform: (_ for _ in ()).throw(AssertionError("expired account must not call provider")),
    )

    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as error:
            await im_service.retry_message(db, user_id, message.id)

    assert error.value.status_code == 409
    assert isinstance(error.value.detail, dict)
    assert error.value.detail["code"] == "ACCOUNT_CREDENTIAL_EXPIRED"


async def _create_account() -> tuple[str, str]:
    user_id = uuid.uuid4().hex
    async with SessionLocal() as db:
        db.add(
            User(
                id=user_id,
                phone=f"132{uuid.uuid4().hex[:8]}",
                password_hash=hash_password("Test@12345"),
                nickname="Cookie 失效测试",
                role="user",
                activated_at=datetime.now(UTC),
            )
        )
        await db.commit()
        account = await publish_repo.create_account(
            db,
            user_id=user_id,
            platform="douyin",
            nickname="待重新授权账号",
            session_json='{"cookie_str":"sessionid=expired"}',
        )
        await im_repo.approve_gray_account(db, account.id, approved_by="admin-test")
    return user_id, account.id


class _BlockingConnection:
    def __init__(self) -> None:
        self.closed = False

    async def listen(self, _callback: object) -> None:
        await asyncio.Event().wait()

    async def close(self) -> None:
        self.closed = True


class _CountingProvider:
    def __init__(self, connection: _BlockingConnection) -> None:
        self.connection = connection
        self.connect_calls = 0

    async def connect(self, _session: dict[str, str]) -> _BlockingConnection:
        self.connect_calls += 1
        return self.connection


class _FakeLease:
    def __init__(self) -> None:
        self.released = False

    async def acquire(self, _account_id: str) -> bool:
        return True

    async def renew(self, _account_id: str) -> bool:
        return True

    async def release(self, _account_id: str) -> bool:
        self.released = True
        return True
