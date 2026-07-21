"""S3-08 atomic IM auto-reply quota reservations."""

import asyncio

from app.modules.im.rate_limit import RedisReplyLimiter


async def test_concurrent_workers_cannot_exceed_atomic_limits() -> None:
    redis = _AtomicFakeRedis()
    limiter_a = RedisReplyLimiter(redis)
    limiter_b = RedisReplyLimiter(redis)

    results = await asyncio.gather(
        *[
            (limiter_a if index % 2 == 0 else limiter_b).reserve(
                account_id="account-1",
                user_id="user-1",
                rule_id="rule-1",
                conversation_id=f"conversation-{index % 2}",
                minute_limit=3,
                daily_limit=50,
                conversation_limit=10,
            )
            for index in range(20)
        ]
    )

    assert sum(results) == 3


async def test_daily_and_conversation_limits_share_the_same_atomic_reservation() -> None:
    redis = _AtomicFakeRedis()
    limiter = RedisReplyLimiter(redis)

    first = await limiter.reserve(
        account_id="account-2",
        user_id="user-2",
        rule_id="rule-2",
        conversation_id="conversation-2",
        minute_limit=10,
        daily_limit=2,
        conversation_limit=1,
    )
    second = await limiter.reserve(
        account_id="account-2",
        user_id="user-2",
        rule_id="rule-2",
        conversation_id="conversation-2",
        minute_limit=10,
        daily_limit=2,
        conversation_limit=1,
    )
    other_conversation = await limiter.reserve(
        account_id="account-2",
        user_id="user-2",
        rule_id="rule-2",
        conversation_id="conversation-3",
        minute_limit=10,
        daily_limit=2,
        conversation_limit=1,
    )
    over_daily = await limiter.reserve(
        account_id="account-2",
        user_id="user-2",
        rule_id="rule-2",
        conversation_id="conversation-4",
        minute_limit=10,
        daily_limit=2,
        conversation_limit=1,
    )

    assert [first, second, other_conversation, over_daily] == [True, False, True, False]


async def test_redis_failure_blocks_auto_reply_instead_of_using_process_memory() -> None:
    limiter = RedisReplyLimiter(_FailingRedis())

    reserved = await limiter.reserve(
        account_id="account-3",
        user_id="user-3",
        rule_id="rule-3",
        conversation_id="conversation-3",
        minute_limit=3,
        daily_limit=50,
        conversation_limit=10,
    )

    assert reserved is False


class _AtomicFakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def eval(self, _script: str, _numkeys: int, *keys_and_args: str) -> int:
        keys = keys_and_args[:3]
        limits = [int(value) for value in keys_and_args[3:6]]
        async with self._lock:
            if any(self.values.get(key, 0) >= limit for key, limit in zip(keys, limits, strict=True)):
                return 0
            for key in keys:
                self.values[key] = self.values.get(key, 0) + 1
            return 1


class _FailingRedis:
    async def eval(self, *_args: object) -> int:
        raise ConnectionError("redis unavailable")
