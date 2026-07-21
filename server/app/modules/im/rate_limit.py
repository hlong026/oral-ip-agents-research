"""Atomic Redis reservations for IM auto-reply quotas."""

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_RESERVE_SCRIPT = """
for i = 1, 3 do
  local current = tonumber(redis.call('get', KEYS[i]) or '0')
  if current >= tonumber(ARGV[i]) then
    return 0
  end
end
for i = 1, 3 do
  redis.call('incr', KEYS[i])
  redis.call('expire', KEYS[i], ARGV[i + 3])
end
return 1
"""


class RedisReplyLimiter:
    """Reserve minute, daily, and conversation capacity in one Lua operation."""

    def __init__(self, redis: Any):
        self._redis = redis

    @classmethod
    def from_url(cls, redis_url: str) -> "RedisReplyLimiter":
        import redis.asyncio as aioredis

        return cls(
            aioredis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
        )

    async def reserve(
        self,
        *,
        account_id: str,
        user_id: str,
        rule_id: str,
        conversation_id: str,
        minute_limit: int,
        daily_limit: int,
        conversation_limit: int,
    ) -> bool:
        now = datetime.now(UTC)
        user_slot = f"{{{user_id}}}"
        minute = now.strftime("%Y%m%d%H%M")
        day = now.strftime("%Y%m%d")
        keys = (
            f"oral:im:quota:{user_slot}:account:{account_id}:minute:{minute}",
            f"oral:im:quota:{user_slot}:rule:{rule_id}:day:{day}",
            f"oral:im:quota:{user_slot}:conversation:{conversation_id}:day:{day}",
        )
        try:
            reserved = await self._redis.eval(
                _RESERVE_SCRIPT,
                3,
                *keys,
                str(max(0, minute_limit)),
                str(max(0, daily_limit)),
                str(max(0, conversation_limit)),
                "120",
                "172800",
                "172800",
            )
            return bool(reserved)
        except Exception as error:  # noqa: BLE001
            logger.warning(
                "IM reply quota reservation failed closed: account=%s error=%s",
                account_id[:8],
                error.__class__.__name__,
            )
            return False
