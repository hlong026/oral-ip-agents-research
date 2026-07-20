"""Mock IM Provider（开发/测试用，定时生成模拟私信）"""
import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

_MOCK_NAMES = ["小明", "粉丝A", "潜在客户", "合作方", "观众甲", "用户xyz"]
_MOCK_MSGS = [
    "你好，请问怎么合作？",
    "价格是多少？",
    "能发一下详细资料吗？",
    "你好，想咨询一下",
    "有没有优惠活动？",
    "视频拍得真好！",
    "怎么联系你们？",
    "可以定制吗？",
]


class MockIMConnection:
    """模拟 WebSocket 连接：每隔 N 秒推送一条假消息"""

    def __init__(self, session: dict[str, Any]):
        self._session = session
        self._alive = True
        self._task: asyncio.Task | None = None

    async def listen(self, on_message: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        logger.info("[MockIM] listener started")
        while self._alive:
            await asyncio.sleep(random.uniform(15, 45))
            if not self._alive:
                break
            uid = str(random.randint(100000000, 999999999))
            msg = {
                "remote_uid": uid,
                "remote_nickname": random.choice(_MOCK_NAMES),
                "remote_avatar": "",
                "msg_type": 7,
                "content": random.choice(_MOCK_MSGS),
                "dy_conversation_id": f"conv_{uid}",
                "dy_conversation_short_id": f"short_{uid}",
                "dy_ticket": "mock_ticket",
            }
            await on_message(msg)

    async def close(self) -> None:
        self._alive = False
        logger.info("[MockIM] listener stopped")

    @property
    def is_alive(self) -> bool:
        return self._alive


class MockIMProvider:
    """Mock 实现：send 只打日志，connect 返回模拟连接"""
    name = "mock_im"
    platform = "douyin"

    async def connect(self, session: dict[str, Any]) -> MockIMConnection:
        return MockIMConnection(session)

    async def send_message(self, session: dict[str, Any], conversation_id: str,
                           conversation_short_id: str, ticket: str,
                           content: str) -> bool:
        logger.info(f"[MockIM] send → conv={conversation_id}: {content[:50]}")
        return True

    async def create_conversation(self, session: dict[str, Any],
                                  to_uid: int) -> dict[str, str]:
        return {
            "conversation_id": f"conv_{to_uid}",
            "conversation_short_id": f"short_{to_uid}",
            "ticket": "mock_ticket",
        }
