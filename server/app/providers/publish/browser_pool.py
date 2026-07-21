"""
浏览器并发池管理
- SAU 每次发布/登录都需要启动 Chromium 实例
- 通过 Semaphore 控制并发数（默认 ≤2），防止资源耗尽
- 生产环境多 Worker 时应替换为 Redis 分布式信号量
"""

import asyncio

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("oral.publish.browser")

settings = get_settings()

# 浏览器并发闸门（发布 + 登录共享）
_browser_gate = asyncio.Semaphore(settings.publish_max_concurrency)


async def acquire_browser_slot() -> None:
    """获取浏览器执行槽位（阻塞等待）"""
    await _browser_gate.acquire()
    logger.debug("browser_slot_acquired", active=2 - _browser_gate._value)


def release_browser_slot() -> None:
    """释放浏览器执行槽位"""
    _browser_gate.release()
    logger.debug("browser_slot_released", active=2 - _browser_gate._value)


class BrowserSlot:
    """异步上下文管理器：自动获取/释放浏览器槽位"""

    async def __aenter__(self) -> "BrowserSlot":
        await acquire_browser_slot()
        return self

    async def __aexit__(self, *exc) -> None:
        release_browser_slot()
