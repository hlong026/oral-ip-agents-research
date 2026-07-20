"""
事件总线（06 文档 §10.1：模块间经领域事件通信）
- 生产：Redis Pub/Sub，notify 模块 WS 网关订阅广播到各端
- 开发：Redis 不可用时回落进程内广播（单进程调试）
"""
import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

CHANNEL_TASKS = "oral:tasks"  # 任务进度/降级事件
CHANNEL_FEED = "oral:feed"    # 任务动态流
CHANNEL_ALERT = "oral:alert"  # 告警（发布失败/额度不足/Provider 降级）
CHANNEL_IM = "oral:im"        # 私信事件（新消息/自动回复/监听状态）

_redis = None
_local_subs: dict[str, set[asyncio.Queue]] = {
    CHANNEL_TASKS: set(), CHANNEL_FEED: set(), CHANNEL_ALERT: set(), CHANNEL_IM: set(),
}


async def init_redis(redis_url: str) -> None:
    global _redis
    try:
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(redis_url, decode_responses=True)
        await _redis.ping()
        logger.info("event bus: redis connected")
    except Exception as e:  # noqa: BLE001
        _redis = None
        logger.warning(f"event bus: redis unavailable ({e}), fallback to in-process broadcast")


async def publish(channel: str, payload: dict) -> None:
    """发布领域事件：trace_id 贯穿"""
    data = json.dumps(payload, ensure_ascii=False, default=str)
    if _redis is not None:
        try:
            await _redis.publish(channel, data)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"redis publish failed ({e}), local fallback")
            _broadcast_local(channel, payload)
    else:
        _broadcast_local(channel, payload)


def _broadcast_local(channel: str, payload: dict) -> None:
    for q in list(_local_subs.get(channel, ())):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass


async def subscribe(channel: str) -> Callable[[], Awaitable[dict | None]]:
    """返回一个异步 get() 函数供 WS 网关消费；本地模式用队列，Redis 模式用 pubsub"""
    if _redis is not None:
        pubsub = _redis.pubsub()
        await pubsub.subscribe(channel)

        async def get_redis() -> dict | None:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg and msg.get("data"):
                try:
                    return json.loads(msg["data"])
                except (ValueError, TypeError):
                    return None
            return None

        return get_redis

    q: asyncio.Queue = asyncio.Queue(maxsize=256)
    _local_subs.setdefault(channel, set()).add(q)

    async def get_local() -> dict | None:
        try:
            return await asyncio.wait_for(q.get(), timeout=1.0)
        except TimeoutError:
            return None

    return get_local
