"""第二阶段站内信、实时通知和账号巡检回归测试。"""

import pytest
import pytest_asyncio
from fastapi import WebSocketDisconnect

from app.core.db import SessionLocal, init_models
from app.core.events import CHANNEL_ALERT, CHANNEL_FEED, CHANNEL_IM, CHANNEL_TASKS, subscribe


@pytest_asyncio.fixture(autouse=True)
async def _database() -> None:
    await init_models()


async def test_notify_user_persists_and_emits_frontend_alert() -> None:
    from app.modules.notify import service

    get_message, unsubscribe = await subscribe(CHANNEL_ALERT)
    try:
        async with SessionLocal() as db:
            await service.notify_user(db, "notify-user", "warn", "登录态失效", "请重新授权")
            stored = await service.list_notifications(db, "notify-user")
        message = await get_message()
    finally:
        await unsubscribe()

    assert len(stored) == 1
    assert stored[0].title == "登录态失效"
    assert message == {
        "kind": "alert",
        "level": "warn",
        "userId": "notify-user",
        "message": "登录态失效",
        "body": "请重新授权",
    }


async def test_account_heartbeat_persists_and_emits_expiry_notice(monkeypatch) -> None:
    from app.modules.notify import service as notify_service
    from app.modules.publish import repository as publish_repo
    from app.providers.publish import heartbeat

    class SelectiveExpiryDriver:
        def __init__(self, expired_account_id: str) -> None:
            self.expired_account_id = expired_account_id

        async def check_cookie_valid(self, _session: dict, *, account_id: str) -> bool:
            return account_id != self.expired_account_id

    async with SessionLocal() as db:
        account = await publish_repo.create_account(
            db,
            user_id="heartbeat-user",
            platform="douyin",
            nickname="巡检账号",
            session_json="{}",
            status="active",
        )
    monkeypatch.setattr(
        heartbeat.registry,
        "publish_driver",
        lambda _platform: SelectiveExpiryDriver(account.id),
    )

    get_message, unsubscribe = await subscribe(CHANNEL_ALERT)
    try:
        await heartbeat.check_all_accounts()
        message = await get_message()
    finally:
        await unsubscribe()

    async with SessionLocal() as db:
        stored_account = await publish_repo.get_account(db, account.id, "heartbeat-user")
        notices = await notify_service.list_notifications(db, "heartbeat-user")

    assert stored_account is not None
    assert stored_account.status == "expired"
    assert len(notices) == 1
    assert notices[0].level == "warn"
    assert message is not None
    assert message["kind"] == "alert"
    assert message["userId"] == "heartbeat-user"


async def test_heartbeat_does_not_expire_account_when_concurrency_gate_is_unavailable(monkeypatch) -> None:
    from app.core.distributed_semaphore import SemaphoreUnavailableError
    from app.modules.notify import service as notify_service
    from app.modules.publish import repository as publish_repo
    from app.providers.publish import heartbeat

    class InfrastructureFailureDriver:
        async def check_cookie_valid(self, _session: dict, *, account_id: str) -> bool:
            del account_id
            raise SemaphoreUnavailableError("redis unavailable")

    async with SessionLocal() as db:
        account = await publish_repo.create_account(
            db,
            user_id="heartbeat-infra-user",
            platform="xiaohongshu",
            nickname="基础设施异常账号",
            session_json="{}",
            status="active",
        )
    monkeypatch.setattr(
        heartbeat.registry,
        "publish_driver",
        lambda _platform: InfrastructureFailureDriver(),
    )

    await heartbeat.check_all_accounts()

    async with SessionLocal() as db:
        stored_account = await publish_repo.get_account(db, account.id, "heartbeat-infra-user")
        notices = await notify_service.list_notifications(db, "heartbeat-infra-user")
    assert stored_account is not None and stored_account.status == "active"
    assert notices == []


async def test_tasks_websocket_waits_for_all_subscription_cleanup(monkeypatch) -> None:
    from app.modules.notify import ws as ws_module

    cleaned_channels: list[str] = []

    async def fake_subscribe(channel: str):
        async def get_message():
            return None

        async def unsubscribe() -> None:
            cleaned_channels.append(channel)

        return get_message, unsubscribe

    class FakeWebSocket:
        headers = {"sec-websocket-protocol": "access-token, test-token"}

        async def accept(self, subprotocol: str) -> None:
            assert subprotocol == "access-token"

        async def receive_text(self) -> str:
            raise WebSocketDisconnect

        async def send_text(self, _payload: str) -> None:
            return None

    async def fake_verify(_token: str) -> str:
        return "notify-user"

    monkeypatch.setattr(ws_module, "verify_ws_token", fake_verify)
    monkeypatch.setattr(ws_module, "subscribe", fake_subscribe)

    await ws_module.tasks_ws(FakeWebSocket())

    assert cleaned_channels == [CHANNEL_TASKS, CHANNEL_FEED, CHANNEL_ALERT, CHANNEL_IM]


async def test_redis_subscription_releases_pubsub_connection(monkeypatch) -> None:
    from app.core import events

    class FakePubSub:
        subscribed_channel = ""
        unsubscribed_channel = ""
        closed = False

        async def subscribe(self, channel: str) -> None:
            self.subscribed_channel = channel

        async def unsubscribe(self, channel: str) -> None:
            self.unsubscribed_channel = channel

        async def aclose(self) -> None:
            self.closed = True

    pubsub = FakePubSub()

    class FakeRedis:
        def pubsub(self) -> FakePubSub:
            return pubsub

    monkeypatch.setattr(events, "_redis", FakeRedis())

    _, unsubscribe = await events.subscribe(CHANNEL_ALERT)
    await unsubscribe()

    assert pubsub.subscribed_channel == CHANNEL_ALERT
    assert pubsub.unsubscribed_channel == CHANNEL_ALERT
    assert pubsub.closed is True


async def test_redis_subscription_failure_releases_pubsub_connection(monkeypatch) -> None:
    from app.core import events

    class FailingPubSub:
        closed = False

        async def subscribe(self, _channel: str) -> None:
            raise RuntimeError("connection exhausted")

        async def aclose(self) -> None:
            self.closed = True

    pubsub = FailingPubSub()

    class FakeRedis:
        def pubsub(self) -> FailingPubSub:
            return pubsub

    monkeypatch.setattr(events, "_redis", FakeRedis())

    with pytest.raises(RuntimeError, match="connection exhausted"):
        await events.subscribe(CHANNEL_ALERT)

    assert pubsub.closed is True


async def test_redis_unsubscribe_failure_still_releases_pubsub_connection(monkeypatch) -> None:
    from app.core import events

    class FailingPubSub:
        closed = False

        async def subscribe(self, _channel: str) -> None:
            return None

        async def unsubscribe(self, _channel: str) -> None:
            raise RuntimeError("connection lost")

        async def aclose(self) -> None:
            self.closed = True

    pubsub = FailingPubSub()

    class FakeRedis:
        def pubsub(self) -> FailingPubSub:
            return pubsub

    monkeypatch.setattr(events, "_redis", FakeRedis())
    _, unsubscribe = await events.subscribe(CHANNEL_ALERT)

    with pytest.raises(RuntimeError, match="connection lost"):
        await unsubscribe()

    assert pubsub.closed is True
