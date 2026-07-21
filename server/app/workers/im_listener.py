"""Independent IM listener supervisor with durable DB intent and Redis leases."""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import and_, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.modules.im.models import IMListenerState
from app.modules.publish.models import PublishAccount

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 30 * 60
RECONCILE_INTERVAL = 5
STATE_POLL_INTERVAL = 5
LEASE_TTL_SECONDS = 30
LEASE_KEY_PREFIX = "oral:im:listener:"

_active_listeners: dict[str, asyncio.Task[None]] = {}
_connections: dict[str, Any] = {}
_default_lease: "RedisListenerLease | None" = None

_RENEW_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


class ListenerLease(Protocol):
    async def acquire(self, account_id: str) -> bool: ...

    async def renew(self, account_id: str) -> bool: ...

    async def release(self, account_id: str) -> bool: ...


class RedisListenerLease:
    """Token-safe per-account lease shared by every listener worker instance."""

    def __init__(self, redis: Any, *, token: str | None = None, ttl_seconds: int = LEASE_TTL_SECONDS):
        self._redis = redis
        self._token = token or uuid.uuid4().hex
        self._ttl_seconds = ttl_seconds

    def _key(self, account_id: str) -> str:
        return f"{LEASE_KEY_PREFIX}{account_id}"

    async def acquire(self, account_id: str) -> bool:
        return bool(
            await self._redis.set(
                self._key(account_id),
                self._token,
                nx=True,
                ex=self._ttl_seconds,
            )
        )

    async def renew(self, account_id: str) -> bool:
        return bool(
            await self._redis.eval(
                _RENEW_SCRIPT,
                1,
                self._key(account_id),
                self._token,
                str(self._ttl_seconds),
            )
        )

    async def release(self, account_id: str) -> bool:
        return bool(await self._redis.eval(_RELEASE_SCRIPT, 1, self._key(account_id), self._token))


def _get_default_lease() -> RedisListenerLease:
    global _default_lease
    if _default_lease is None:
        import redis.asyncio as aioredis

        client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
        _default_lease = RedisListenerLease(client)
    return _default_lease


def start_listening(account_id: str, user_id: str, lease: RedisListenerLease | None = None) -> bool:
    """Start one worker-local task; the Redis lease prevents cross-worker duplication."""
    existing = _active_listeners.get(account_id)
    if existing and not existing.done():
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("[IMWorker] no running event loop, cannot start listener")
        return False
    task = loop.create_task(_listen_loop(account_id, user_id, lease or _get_default_lease()))
    _active_listeners[account_id] = task
    return True


def stop_listening(account_id: str) -> None:
    """Stop a worker-local task; API stop requests persist intent instead."""
    task = _active_listeners.get(account_id)
    if task and not task.done():
        task.cancel()


async def shutdown_all() -> None:
    tasks = list(_active_listeners.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _active_listeners.clear()
    _connections.clear()


async def reconcile_listeners(lease: RedisListenerLease | None = None) -> None:
    """Ensure every valid durable listening intent has a worker-local task."""
    if not get_settings().im_enabled:
        return
    async with SessionLocal() as db:
        result = await db.execute(
            select(IMListenerState)
            .join(
                PublishAccount,
                and_(
                    PublishAccount.id == IMListenerState.account_id,
                    PublishAccount.user_id == IMListenerState.user_id,
                ),
            )
            .where(
                IMListenerState.status == "listening",
                PublishAccount.status == "active",
            )
        )
        states = list(result.scalars().all())

    for state in states:
        if lease is None:
            start_listening(state.account_id, state.user_id)
        else:
            start_listening(state.account_id, state.user_id, lease)


async def restore_listeners() -> None:
    """Compatibility alias for tests and operational scripts."""
    await reconcile_listeners()


async def run_supervisor() -> None:
    """Run the dedicated listener reconciliation loop."""
    if not get_settings().im_enabled:
        logger.info("[IMWorker] IM_ENABLED=false; supervisor stopped")
        return
    lease = _get_default_lease()
    try:
        while True:
            try:
                await reconcile_listeners(lease)
            except Exception:  # noqa: BLE001
                logger.exception("[IMWorker] reconcile failed")
            await asyncio.sleep(RECONCILE_INTERVAL)
    finally:
        await shutdown_all()


async def _listener_intent_active(account_id: str, user_id: str) -> bool:
    async with SessionLocal() as db:
        result = await db.execute(
            select(IMListenerState.id)
            .join(
                PublishAccount,
                and_(
                    PublishAccount.id == IMListenerState.account_id,
                    PublishAccount.user_id == IMListenerState.user_id,
                ),
            )
            .where(
                IMListenerState.account_id == account_id,
                IMListenerState.user_id == user_id,
                IMListenerState.status == "listening",
                PublishAccount.status == "active",
            )
        )
        return result.scalar_one_or_none() is not None


async def _load_account_context(account_id: str, user_id: str) -> tuple[dict[str, Any], str] | None:
    from app.modules.publish import repository as publish_repo

    async with SessionLocal() as db:
        account = await publish_repo.get_account(db, account_id, user_id)
        if not account or account.status != "active":
            return None
        return publish_repo.account_session(account), account.platform


async def _check_cookie_validity(session: dict[str, Any]) -> bool:
    import httpx

    cookie_str = session.get("cookie_str", "")
    if not cookie_str:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                "https://www.douyin.com/aweme/v1/web/user/profile/self/",
                headers={"Cookie": cookie_str, "User-Agent": "Mozilla/5.0"},
            )
        data = response.json()
        return response.status_code == 200 and data.get("status_code", -1) == 0
    except (httpx.HTTPError, ValueError, TypeError):
        return False


async def _mark_cookie_expired(account_id: str, user_id: str) -> None:
    from app.core.events import publish as emit
    from app.modules.im import repository as im_repo
    from app.modules.im.events import CHANNEL_IM, EV_LISTENER_STATUS

    async with SessionLocal() as db:
        await im_repo.upsert_listener_state(
            db,
            account_id=account_id,
            user_id=user_id,
            status="error",
            error_msg="cookie_expired",
        )
    await emit(
        CHANNEL_IM,
        {
            "kind": EV_LISTENER_STATUS,
            "userId": user_id,
            "accountId": account_id,
            "status": "error",
            "errorMsg": "登录态失效，请重新绑定账号",
        },
    )


async def _set_listener_error(account_id: str, user_id: str, error: Exception) -> None:
    from app.modules.im import repository as im_repo

    async with SessionLocal() as db:
        await im_repo.upsert_listener_state(
            db,
            account_id=account_id,
            user_id=user_id,
            status="error",
            error_msg=str(error)[:200],
        )


async def _listen_loop(account_id: str, user_id: str, lease: ListenerLease) -> None:
    current_task = asyncio.current_task()
    connection: Any | None = None
    listen_task: asyncio.Task[None] | None = None
    try:
        if not await lease.acquire(account_id):
            return

        context = await _load_account_context(account_id, user_id)
        if context is None:
            return
        session, platform = context

        from app.providers.registry import registry

        try:
            provider = registry.im_driver(platform)
        except Exception as error:  # noqa: BLE001
            await _set_listener_error(account_id, user_id, error)
            return
        retry_count = 0
        last_heartbeat = asyncio.get_running_loop().time()

        while await _listener_intent_active(account_id, user_id):
            try:
                connection = await provider.connect(session)
                _connections[account_id] = connection

                async def on_message(message: dict[str, Any]) -> None:
                    from app.modules.im.service import handle_incoming_message

                    await handle_incoming_message(
                        account_id=account_id,
                        user_id=user_id,
                        remote_uid=message.get("remote_uid", ""),
                        remote_nickname=message.get("remote_nickname", ""),
                        remote_avatar=message.get("remote_avatar", ""),
                        msg_type=message.get("msg_type", 7),
                        content=message.get("content", ""),
                        dy_conversation_id=message.get("dy_conversation_id", ""),
                        dy_conversation_short_id=message.get("dy_conversation_short_id", ""),
                        dy_ticket=message.get("dy_ticket", ""),
                    )

                listen_task = asyncio.create_task(connection.listen(on_message))
                while True:
                    done, _pending = await asyncio.wait({listen_task}, timeout=STATE_POLL_INTERVAL)
                    if done:
                        await listen_task
                        break
                    retry_count = 0
                    if not await _listener_intent_active(account_id, user_id):
                        return
                    if not await lease.renew(account_id):
                        logger.warning("[IMWorker] listener lease lost for %s", account_id[:8])
                        return

                    now = asyncio.get_running_loop().time()
                    if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                        if not await _check_cookie_validity(session):
                            await _mark_cookie_expired(account_id, user_id)
                            return
                        last_heartbeat = now
                        from app.modules.im import repository as im_repo

                        async with SessionLocal() as db:
                            await im_repo.upsert_listener_state(
                                db,
                                account_id=account_id,
                                user_id=user_id,
                                status="listening",
                                last_heartbeat=datetime.now(UTC),
                            )
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001
                retry_count += 1
                if retry_count > 5:
                    logger.exception("[IMWorker] max retries exceeded for %s", account_id[:8])
                    await _set_listener_error(account_id, user_id, error)
                    return
                await asyncio.sleep(min(10 * retry_count, 60))
            finally:
                if connection is not None:
                    try:
                        await connection.close()
                    except Exception:  # noqa: BLE001
                        logger.warning("[IMWorker] connection close failed", exc_info=True)
                connection = None
                _connections.pop(account_id, None)
                if listen_task is not None and not listen_task.done():
                    listen_task.cancel()
                    await asyncio.gather(listen_task, return_exceptions=True)
                listen_task = None
    finally:
        try:
            await lease.release(account_id)
        except Exception:  # noqa: BLE001
            logger.warning("[IMWorker] listener lease release failed", exc_info=True)
        if _active_listeners.get(account_id) is current_task:
            _active_listeners.pop(account_id, None)


def get_active_count() -> int:
    return sum(1 for task in _active_listeners.values() if not task.done())


if __name__ == "__main__":
    asyncio.run(run_supervisor())
