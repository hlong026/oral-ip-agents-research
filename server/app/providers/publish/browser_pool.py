"""
浏览器并发池管理
- SAU 每次发布/登录都需要启动 Chromium 实例
- 生产通过 Redis 跨 Worker 控制发布与巡检并发数（默认 ≤2），防止资源耗尽
"""

from app.core.config import get_settings
from app.core.distributed_semaphore import DistributedSemaphore, SemaphoreLease
from app.core.logging import get_logger
from app.core.runtime_limits import PUBLISH_SEMAPHORE_LEASE_SECONDS

logger = get_logger("oral.publish.browser")

settings = get_settings()

# 浏览器并发闸门（发布 + 登录共享）
_browser_gate = DistributedSemaphore(
    "publish-browser",
    limit=settings.publish_max_concurrency,
    lease_seconds=PUBLISH_SEMAPHORE_LEASE_SECONDS,
)


async def acquire_browser_slot() -> SemaphoreLease:
    """获取浏览器执行槽位（阻塞等待）"""
    lease = await _browser_gate.acquire()
    logger.debug("browser_slot_acquired")
    return lease


async def release_browser_slot(lease: SemaphoreLease) -> None:
    """释放浏览器执行槽位"""
    await lease.release()
    logger.debug("browser_slot_released")


class BrowserSlot:
    """异步上下文管理器：自动获取/释放浏览器槽位"""

    def __init__(self) -> None:
        self._lease: SemaphoreLease | None = None

    async def __aenter__(self) -> "BrowserSlot":
        self._lease = await acquire_browser_slot()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._lease is not None:
            await release_browser_slot(self._lease)
            self._lease = None
