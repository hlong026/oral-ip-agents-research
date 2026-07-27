"""跨进程并发闸门回归测试。"""

import asyncio
import os
import time
import uuid

import pytest

from app.core.distributed_semaphore import DistributedSemaphore, SemaphoreUnavailableError


class FakeRedis:
    def __init__(self) -> None:
        self.members: dict[str, dict[str, int]] = {}

    async def eval(self, script: str, _numkeys: int, key: str, *args: object) -> int:
        if "ZCARD" in script:
            limit, lease_ms, token = int(args[0]), int(args[1]), str(args[2])
            now_ms = int(time.time() * 1000)
            members = self.members.setdefault(key, {})
            members = {member: expiry for member, expiry in members.items() if expiry > now_ms}
            self.members[key] = members
            if len(members) >= limit:
                return 0
            members[token] = now_ms + lease_ms
            return 1
        self.members.setdefault(key, {}).pop(str(args[0]), None)
        return 1


async def test_independent_process_gates_share_one_global_limit() -> None:
    redis = FakeRedis()
    first = DistributedSemaphore(
        "pipeline",
        limit=1,
        lease_seconds=30,
        poll_interval=0.01,
        redis_client=redis,
        distributed=True,
    )
    second = DistributedSemaphore(
        "pipeline",
        limit=1,
        lease_seconds=30,
        poll_interval=0.01,
        redis_client=redis,
        distributed=True,
    )

    first_lease = await first.acquire()
    waiting = asyncio.create_task(second.acquire())
    await asyncio.sleep(0.03)
    assert waiting.done() is False

    await first_lease.release()
    second_lease = await asyncio.wait_for(waiting, timeout=0.2)
    await second_lease.release()


async def test_production_gate_fails_closed_when_redis_is_unavailable() -> None:
    class FailingRedis:
        async def eval(self, *_args: object) -> int:
            raise ConnectionError("redis unavailable")

    gate = DistributedSemaphore(
        "pipeline",
        limit=1,
        redis_client=FailingRedis(),
        distributed=True,
    )

    with pytest.raises(SemaphoreUnavailableError, match="分布式并发闸门不可用"):
        await gate.acquire()


async def test_gate_operation_has_a_bounded_timeout() -> None:
    class HangingRedis:
        async def eval(self, *_args: object) -> int:
            await asyncio.Future()
            return 0

    gate = DistributedSemaphore(
        "pipeline",
        limit=1,
        redis_client=HangingRedis(),
        distributed=True,
        operation_timeout=0.02,
    )

    with pytest.raises(SemaphoreUnavailableError, match="分布式并发闸门不可用"):
        await gate.acquire()


def test_gate_leases_outlive_their_actor_time_limits() -> None:
    from app.core.runtime_limits import (
        PIPELINE_ACTOR_TIME_LIMIT_MS,
        PIPELINE_SEMAPHORE_LEASE_SECONDS,
        PUBLISH_ACTOR_TIME_LIMIT_MS,
        PUBLISH_SEMAPHORE_LEASE_SECONDS,
    )

    assert PIPELINE_SEMAPHORE_LEASE_SECONDS * 1000 > PIPELINE_ACTOR_TIME_LIMIT_MS
    assert PUBLISH_SEMAPHORE_LEASE_SECONDS * 1000 > PUBLISH_ACTOR_TIME_LIMIT_MS


@pytest.mark.skipif(not os.getenv("TEST_REDIS_URL"), reason="requires an explicit disposable Redis")
async def test_real_redis_enforces_and_releases_global_limit() -> None:
    import redis.asyncio as aioredis

    redis = aioredis.from_url(os.environ["TEST_REDIS_URL"], decode_responses=True)
    name = f"integration-{uuid.uuid4().hex}"
    first = DistributedSemaphore(name, limit=1, redis_client=redis, distributed=True)
    second = DistributedSemaphore(name, limit=1, redis_client=redis, distributed=True)
    try:
        first_lease = await first.acquire()
        waiting = asyncio.create_task(second.acquire())
        await asyncio.sleep(0.05)
        assert waiting.done() is False
        await first_lease.release()
        second_lease = await asyncio.wait_for(waiting, timeout=1)
        await second_lease.release()
    finally:
        await redis.aclose()
