"""Redis-backed counting semaphore with a local dev/test fallback."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("oral.distributed_semaphore")

_ACQUIRE_SCRIPT = """
local now = redis.call('TIME')
local now_ms = (tonumber(now[1]) * 1000) + math.floor(tonumber(now[2]) / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now_ms)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then
  return 0
end
redis.call('ZADD', KEYS[1], now_ms + tonumber(ARGV[2]), ARGV[3])
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[2]) + 1000)
return 1
"""

_RELEASE_SCRIPT = """
return redis.call('ZREM', KEYS[1], ARGV[1])
"""


class SemaphoreUnavailableError(RuntimeError):
    """Redis cannot currently enforce the production-wide concurrency limit."""


class SemaphoreLease:
    def __init__(
        self,
        gate: "DistributedSemaphore",
        *,
        token: str | None,
    ) -> None:
        self._gate = gate
        self._token = token
        self._released = False

    async def release(self) -> None:
        if self._released:
            return
        self._released = True
        await self._gate._release(self._token)


class DistributedSemaphore:
    """Bound concurrency across workers; a crashed holder expires after the lease."""

    def __init__(
        self,
        name: str,
        *,
        limit: int,
        lease_seconds: int = 1_860,
        poll_interval: float = 0.25,
        redis_client: Any | None = None,
        distributed: bool | None = None,
        operation_timeout: float | None = None,
    ) -> None:
        settings = get_settings()
        self._key = f"{settings.task_queue_name}:semaphore:{name}"
        self._limit = max(1, limit)
        self._lease_ms = max(1, lease_seconds) * 1000
        self._poll_interval = max(0.01, poll_interval)
        self._redis = redis_client
        self._redis_url = settings.redis_url
        self._operation_timeout = max(
            0.05,
            operation_timeout
            if operation_timeout is not None
            else settings.redis_operation_timeout_seconds,
        )
        self._distributed = (
            settings.app_env not in {"dev", "test"} if distributed is None else distributed
        )
        self._local = asyncio.Semaphore(self._limit)

    def _redis_client(self) -> Any:
        if self._redis is None:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=self._operation_timeout,
                socket_timeout=self._operation_timeout,
            )
        return self._redis

    async def acquire(self) -> SemaphoreLease:
        if not self._distributed:
            await self._local.acquire()
            return SemaphoreLease(self, token=None)

        token = uuid.uuid4().hex
        redis = self._redis_client()
        while True:
            try:
                acquired = await asyncio.wait_for(
                    redis.eval(
                        _ACQUIRE_SCRIPT,
                        1,
                        self._key,
                        self._limit,
                        self._lease_ms,
                        token,
                    ),
                    timeout=self._operation_timeout,
                )
            except Exception as exc:
                logger.exception("distributed_semaphore_acquire_failed", key=self._key)
                raise SemaphoreUnavailableError("分布式并发闸门不可用") from exc
            if int(acquired or 0) == 1:
                return SemaphoreLease(self, token=token)
            await asyncio.sleep(self._poll_interval)

    async def _release(self, token: str | None) -> None:
        if token is None:
            self._local.release()
            return
        try:
            await asyncio.wait_for(
                self._redis_client().eval(_RELEASE_SCRIPT, 1, self._key, token),
                timeout=self._operation_timeout,
            )
        except Exception:
            # Lease has a bounded TTL, so a release outage cannot leak a slot forever.
            logger.exception("distributed_semaphore_release_failed", key=self._key)

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        lease = await self.acquire()
        try:
            yield
        finally:
            await lease.release()
