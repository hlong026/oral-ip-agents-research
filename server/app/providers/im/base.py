"""IM Provider 抽象协议（防供应商锁定）"""

from collections.abc import Awaitable, Callable
from typing import Any, Protocol


class IMConnection(Protocol):
    """WebSocket 长连接抽象"""

    async def listen(self, on_message: Callable[[dict[str, Any]], Awaitable[None]]) -> None: ...
    async def close(self) -> None: ...

    @property
    def is_alive(self) -> bool: ...


class IMProvider(Protocol):
    """平台私信能力抽象"""

    name: str
    platform: str

    async def connect(self, session: dict[str, Any]) -> IMConnection: ...

    async def send_message(
        self,
        session: dict[str, Any],
        conversation_id: str,
        conversation_short_id: str,
        ticket: str,
        content: str,
        remote_uid: str = "",
        remote_nickname: str = "",
    ) -> bool: ...

    async def sync_messages(self, session: dict[str, Any], limit: int = 100) -> list[dict[str, Any]]: ...

    async def create_conversation(self, session: dict[str, Any], to_uid: int) -> dict[str, str]: ...
