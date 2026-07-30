"""S3-04 persistent IM listener supervision."""

import asyncio
import uuid

import pytest
from httpx import AsyncClient

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.main import app, lifespan, settings
from app.modules.auth.models import User
from app.modules.im import repository as im_repo
from app.modules.im.models import IMListenerState
from app.modules.im.schemas import ListenerControlIn
from app.modules.im.service import start_listener, stop_listener
from app.modules.publish import repository as publish_repo
from app.workers import im_listener


async def _create_account() -> tuple[str, str]:
    user_id = uuid.uuid4().hex
    async with SessionLocal() as db:
        db.add(
            User(
                id=user_id,
                phone=f"136{uuid.uuid4().hex[:8]}",
                password_hash=hash_password("Test@12345"),
                nickname="监听测试",
                role="user",
            )
        )
        await db.commit()
        account = await publish_repo.create_account(
            db,
            user_id=user_id,
            platform="douyin",
            nickname="监听账号",
            session_json='{"cookie_str":"sessionid=test","device_id":"1234567890123456789"}',
        )
        await im_repo.approve_gray_account(db, account.id, approved_by="admin-test")
    return user_id, account.id


async def test_api_only_persists_listener_intent(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    del client
    user_id, account_id = await _create_account()

    def unexpected_runtime_call(*_args: object) -> None:
        raise AssertionError("API process must not own IM connections")

    monkeypatch.setattr(im_listener, "start_listening", unexpected_runtime_call)
    monkeypatch.setattr(im_listener, "stop_listening", unexpected_runtime_call)

    async with SessionLocal() as db:
        started = await start_listener(db, user_id, ListenerControlIn(accountId=account_id))
    assert started.status == "listening"

    monkeypatch.setattr(settings, "im_enabled", True)
    monkeypatch.setattr(settings, "douyin_im_app_key", "contract-test-key")
    monkeypatch.setattr(im_listener, "restore_listeners", unexpected_runtime_call)
    monkeypatch.setattr(im_listener, "shutdown_all", unexpected_runtime_call)
    async with lifespan(app):
        pass

    async with SessionLocal() as db:
        state = await im_repo.get_listener_state(db, account_id, user_id)
        assert state is not None
        assert state.status == "listening"
        stopped = await stop_listener(db, user_id, ListenerControlIn(accountId=account_id))
    assert stopped.status == "disconnected"


async def test_listener_state_cannot_be_reassigned_to_another_user(client: AsyncClient) -> None:
    del client
    owner_id, account_id = await _create_account()
    attacker_id = uuid.uuid4().hex
    async with SessionLocal() as db:
        db.add(IMListenerState(account_id=account_id, user_id=owner_id, status="listening"))
        await db.commit()

        with pytest.raises(im_repo.ListenerOwnershipConflict):
            await im_repo.upsert_listener_state(
                db,
                account_id=account_id,
                user_id=attacker_id,
                status="disconnected",
            )

        state = await im_repo.get_listener_state(db, account_id, owner_id)
        assert state is not None
        assert state.user_id == owner_id
        assert state.status == "listening"
        state.status = "disconnected"
        await db.commit()


async def test_reconcile_does_not_restore_error_state(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    del client
    user_id, account_id = await _create_account()
    started: list[tuple[str, str]] = []

    async with SessionLocal() as db:
        db.add(IMListenerState(account_id=account_id, user_id=user_id, status="error"))
        await db.commit()

    monkeypatch.setattr(settings, "im_enabled", True)
    monkeypatch.setattr(im_listener, "start_listening", lambda account, user, *_args: started.append((account, user)))

    await im_listener.reconcile_listeners(_FakeLease())

    assert started == []


async def test_redis_listener_lease_has_single_token_owner() -> None:
    redis = _FakeRedis()
    first = im_listener.RedisListenerLease(redis, token="worker-a", ttl_seconds=60)
    second = im_listener.RedisListenerLease(redis, token="worker-b", ttl_seconds=60)

    assert await first.acquire("account-1") is True
    assert await second.acquire("account-1") is False
    assert await second.renew("account-1") is False
    assert await second.release("account-1") is False
    assert await first.renew("account-1") is True
    assert await first.release("account-1") is True
    assert await second.acquire("account-1") is True


async def test_running_listener_observes_persisted_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _BlockingConnection()
    lease = _FakeLease()
    checks = 0

    async def load_context(_account_id: str, _user_id: str) -> tuple[dict[str, str], str]:
        return {"cookie_str": "sessionid=test"}, "douyin"

    async def intent_active(_account_id: str, _user_id: str) -> bool:
        nonlocal checks
        checks += 1
        return checks == 1

    class Provider:
        async def connect(self, _session: dict[str, str]) -> _BlockingConnection:
            return connection

    from app.providers.registry import registry

    monkeypatch.setattr(im_listener, "_load_account_context", load_context)
    monkeypatch.setattr(im_listener, "_listener_intent_active", intent_active)
    monkeypatch.setattr(im_listener, "STATE_POLL_INTERVAL", 0.001)
    monkeypatch.setattr(registry, "im_driver", lambda _platform: Provider())

    await asyncio.wait_for(im_listener._listen_loop("account-1", "user-1", lease), timeout=1)

    assert connection.closed is True
    assert lease.released is True


@pytest.mark.parametrize(
    ("connection", "expected_terminal_metric"),
    [
        pytest.param(None, "listener_connect_failure", id="connect-failure"),
        pytest.param("listen-failure", "listener_error", id="listen-failure"),
    ],
)
async def test_listener_failure_paths_record_real_metric_kind(
    monkeypatch: pytest.MonkeyPatch,
    connection: str | None,
    expected_terminal_metric: str,
) -> None:
    lease = _FakeLease()
    checks = 0
    metrics: list[str] = []

    async def intent_active(_account_id: str, _user_id: str) -> bool:
        nonlocal checks
        checks += 1
        return checks == 1

    async def record_metric(kind: str, *_args: str) -> None:
        metrics.append(kind)

    async def no_sleep(_seconds: float) -> None:
        return None

    class Provider:
        async def connect(self, _session: dict[str, str]) -> _FailingListenConnection:
            if connection is None:
                raise RuntimeError("connect failed")
            return _FailingListenConnection()

    from app.providers.registry import registry

    monkeypatch.setattr(im_listener, "_load_account_context", _load_test_context)
    monkeypatch.setattr(im_listener, "_listener_intent_active", intent_active)
    monkeypatch.setattr(im_listener, "_record_metric", record_metric)
    monkeypatch.setattr(im_listener.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(registry, "im_driver", lambda _platform: Provider())

    await im_listener._listen_loop("account-metric", "user-metric", lease)

    assert metrics[0] == "listener_connect_attempt"
    if connection is not None:
        assert "listener_connected" in metrics
    assert expected_terminal_metric in metrics


async def test_listener_clean_disconnect_records_connection_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    lease = _FakeLease()
    checks = 0
    metrics: list[str] = []

    async def intent_active(_account_id: str, _user_id: str) -> bool:
        nonlocal checks
        checks += 1
        return checks == 1

    async def record_metric(kind: str, *_args: str) -> None:
        metrics.append(kind)

    class Provider:
        async def connect(self, _session: dict[str, str]) -> _ImmediateConnection:
            return _ImmediateConnection()

    from app.providers.registry import registry

    monkeypatch.setattr(im_listener, "_load_account_context", _load_test_context)
    monkeypatch.setattr(im_listener, "_listener_intent_active", intent_active)
    monkeypatch.setattr(im_listener, "_record_metric", record_metric)
    monkeypatch.setattr(registry, "im_driver", lambda _platform: Provider())

    await im_listener._listen_loop("account-metric", "user-metric", lease)

    assert metrics == ["listener_connect_attempt", "listener_connected", "listener_disconnected"]


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, *, nx: bool, ex: int) -> bool:
        del ex
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, _script: str, _numkeys: int, key: str, token: str, *args: str) -> int:
        if self.values.get(key) != token:
            return 0
        if args:
            return 1
        del self.values[key]
        return 1


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


class _BlockingConnection:
    def __init__(self) -> None:
        self.closed = False

    async def listen(self, _callback: object) -> None:
        await asyncio.Event().wait()

    async def close(self) -> None:
        self.closed = True


class _ImmediateConnection:
    async def listen(self, _callback: object) -> None:
        return None

    async def close(self) -> None:
        return None


class _FailingListenConnection:
    async def listen(self, _callback: object) -> None:
        raise RuntimeError("listen failed")

    async def close(self) -> None:
        return None


async def _load_test_context(_account_id: str, _user_id: str) -> tuple[dict[str, str], str]:
    return {}, "douyin"
