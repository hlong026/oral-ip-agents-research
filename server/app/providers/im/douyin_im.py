"""抖音 IM Provider（整合 DouYin_Spider 的 WebSocket + Protobuf 逻辑）
- connect(): 建立 wss://frontier-im.douyin.com/ws/v2 长连接
- send_message(): POST https://imapi.douyin.com/v1/message/send
- create_conversation(): POST https://imapi.douyin.com/v2/conversation/create
"""

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# 抖音 IM 常量
IM_WS_URL = "wss://frontier-im.douyin.com/ws/v2"
IM_SEND_URL = "https://imapi.douyin.com/v1/message/send"
IM_CONV_CREATE_URL = "https://imapi.douyin.com/v2/conversation/create"
IM_DEVICE_URL = "https://mcs.zijieapi.com/v1/device/register"

COMMON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.douyin.com/",
    "Origin": "https://www.douyin.com",
}


def _get_im_constants() -> tuple[str, str, str]:
    """#11 从配置读取 IM 常量"""
    s = get_settings()
    return s.douyin_im_app_key, s.douyin_im_aid, s.douyin_im_fpid


def _compute_access_key(device_id: str, session_id: str) -> str:
    """#11 access_key = md5(fpid + appKey + deviceId + session_id)"""
    app_key, _aid, fpid = _get_im_constants()
    raw = fpid + app_key + device_id + session_id
    return hashlib.md5(raw.encode()).hexdigest()


class DouyinIMConnection:
    """抖音 WebSocket 长连接"""

    def __init__(self, session: dict[str, Any]):
        self._session = session
        self._alive = False
        self._ws: Any | None = None

    async def listen(self, on_message: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        """建立 WebSocket 并持续监听私信"""
        try:
            import websockets
        except ImportError:
            logger.error("websockets 未安装，无法启动抖音 IM 监听")
            return

        cookie_str = self._session.get("cookie_str", "")
        session_id = self._session.get("sessionid", "")
        device_id = self._session.get("device_id", "")

        if not session_id:
            # 从 cookie_str 提取 sessionid
            for part in cookie_str.split(";"):
                kv = part.strip().split("=", 1)
                if len(kv) == 2 and kv[0] == "sessionid":
                    session_id = kv[1]
                    break

        if not device_id:
            device_id = await self._fetch_device_id(cookie_str)
            self._session["device_id"] = device_id

        access_key = _compute_access_key(device_id, session_id)
        _app_key, aid, fpid = _get_im_constants()
        ws_url = (
            f"{IM_WS_URL}?aid={aid}&device_platform=douyin_pc&fpid={fpid}"
            f"&device_id={device_id}&token={session_id}&access_key={access_key}"
        )

        self._alive = True
        logger.info(f"[DouyinIM] connecting ws device_id={device_id[:8]}...")

        while self._alive:
            try:
                async with websockets.connect(
                    ws_url,
                    additional_headers={"Cookie": cookie_str},
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self._ws = ws
                    logger.info("[DouyinIM] ws connected")
                    async for raw in ws:
                        if not self._alive:
                            break
                        parsed = self._decode_frame(raw)
                        if parsed:
                            await on_message(parsed)
            except Exception as e:  # noqa: BLE001
                if self._alive:
                    logger.warning(f"[DouyinIM] ws error: {e}, reconnect in 10s")
                    import asyncio

                    await asyncio.sleep(10)

    def _decode_frame(self, raw: bytes | str) -> dict[str, Any] | None:
        """Reject frames until a fixed, versioned Proto contract is available.

        Dynamic black-box decoding was both dependency-incompatible and unsafe:
        arbitrary field guesses cannot prove the sender or message contract.
        """
        logger.debug("[DouyinIM] dropped undecodable frame bytes=%d", len(raw))
        return None

    def _extract_message(self, data: dict) -> dict[str, Any] | None:
        """从解码后的 protobuf dict 中提取私信字段"""
        # 结构依赖实际 proto，此处为占位逻辑
        # 生产需按 PushFrame → Response → new_message_notify.message 路径解析
        try:
            msg_list = data.get("1", {}).get("1", [])
            if not msg_list:
                return None
            msg = msg_list[0] if isinstance(msg_list, list) else msg_list
            ext = json.loads(msg.get("8", "{}"))
            content = ext.get("content", "")
            return {
                "remote_uid": str(ext.get("from_uid", "")),
                "remote_nickname": ext.get("from_nickname", ""),
                "remote_avatar": ext.get("from_avatar", ""),
                "msg_type": int(ext.get("msg_type", 7)),
                "content": content,
                "dy_conversation_id": str(ext.get("conversation_id", "")),
                "dy_conversation_short_id": str(ext.get("conversation_short_id", "")),
                "dy_ticket": str(ext.get("ticket", "")),
            }
        except Exception:  # noqa: BLE001
            return None

    async def _fetch_device_id(self, cookie_str: str) -> str:
        """获取设备 ID（简化：生成随机 device_id）"""
        import random

        return str(random.randint(10**18, 10**19 - 1))

    async def close(self) -> None:
        self._alive = False
        if self._ws:
            await self._ws.close()
        logger.info("[DouyinIM] ws closed")

    @property
    def is_alive(self) -> bool:
        return self._alive


class DouyinIMProvider:
    """抖音私信 Provider 实现"""

    name = "douyin_im"
    platform = "douyin"

    async def connect(self, session: dict[str, Any]) -> DouyinIMConnection:
        return DouyinIMConnection(session)

    async def send_message(
        self, session: dict[str, Any], conversation_id: str, conversation_short_id: str, ticket: str, content: str
    ) -> bool:
        """通过 imapi 发送文本消息"""
        cookie_str = session.get("cookie_str", "")
        # 构建发送请求（简化版，生产需 Protobuf 编码 + web_protect 签名）
        payload = {
            "conversation_id": conversation_id,
            "conversation_short_id": conversation_short_id,
            "content": json.dumps({"text": content}, ensure_ascii=False),
            "msg_type": 7,
            "ticket": ticket,
        }
        headers = {**COMMON_HEADERS, "Cookie": cookie_str, "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(IM_SEND_URL, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status_code") == 0:
                    return True
                logger.warning(f"[DouyinIM] send failed: {data}")
            else:
                logger.warning(f"[DouyinIM] send http {resp.status_code}")
        return False

    async def create_conversation(self, session: dict[str, Any], to_uid: int) -> dict[str, str]:
        """创建会话（cmd=609）"""
        cookie_str = session.get("cookie_str", "")
        payload = {"to_user_id": to_uid, "cmd": 609}
        headers = {**COMMON_HEADERS, "Cookie": cookie_str, "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(IM_CONV_CREATE_URL, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "conversation_id": str(data.get("conversation_id", "")),
                    "conversation_short_id": str(data.get("conversation_short_id", "")),
                    "ticket": str(data.get("ticket", "")),
                }
        return {"conversation_id": "", "conversation_short_id": "", "ticket": ""}
