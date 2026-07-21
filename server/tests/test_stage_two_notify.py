"""第二阶段站内信、实时通知和账号巡检回归测试。"""

import pytest_asyncio

from app.core.db import SessionLocal, init_models
from app.core.events import CHANNEL_ALERT, subscribe


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
        unsubscribe()

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
        unsubscribe()

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
