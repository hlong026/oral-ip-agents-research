"""抖音私信接收适配器。

协议字段来自本地 DouYin_Spider：Playwright 登录态需要先规范化，
再用固定客户端参数连接 frontier-im WebSocket 并解析 Protobuf 推送。
"""

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast
from urllib.parse import urlencode

from google.protobuf.message import DecodeError

from app.core.config import get_settings
from app.providers.im.douyin_browser import DouyinBrowserIMClient
from app.providers.im.proto import Live_pb2, Response_pb2

logger = logging.getLogger(__name__)

IM_WS_URL = "wss://frontier-im.douyin.com/ws/v2"
DOUYIN_ORIGIN = "https://www.douyin.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def _parse_cookie_string(cookie_str: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for part in cookie_str.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name:
            cookies[name] = value
    return cookies


def normalize_douyin_session(session: dict[str, Any]) -> dict[str, Any]:
    """把 Playwright storage_state 转成抖音 IM 使用的 Cookie 登录态。"""
    normalized = dict(session)
    cookie_map = _parse_cookie_string(str(session.get("cookie_str", "")))

    for cookie in session.get("cookies", []):
        if not isinstance(cookie, dict):
            continue
        domain = str(cookie.get("domain", "")).lstrip(".").lower()
        name = str(cookie.get("name", ""))
        if name and (domain == "douyin.com" or domain.endswith(".douyin.com")):
            cookie_map[name] = str(cookie.get("value", ""))

    session_id = str(session.get("sessionid") or cookie_map.get("sessionid") or cookie_map.get("sessionid_ss") or "")
    if not session_id:
        raise ValueError("抖音登录态缺少 sessionid，请重新扫码绑定账号")

    normalized["sessionid"] = session_id
    normalized["cookie_str"] = "; ".join(f"{name}={value}" for name, value in cookie_map.items())
    device_id = str(session.get("device_id", ""))
    if not device_id:
        for origin in session.get("origins", []):
            for item in origin.get("localStorage", []):
                if item.get("name") == "oral_im_device_id":
                    device_id = str(item.get("value", ""))
                    break
            if device_id:
                break
    if device_id:
        normalized["device_id"] = device_id
    return normalized


def compute_access_key(
    device_id: str,
    *,
    app_key: str,
    fpid: str,
    suffix: str,
) -> str:
    """按 DouYin_Spider 的 frontier-im access_key 公式计算摘要。"""
    raw = f"{fpid}{app_key}{device_id}{suffix}"
    return hashlib.md5(raw.encode()).hexdigest()


class DouyinIMConnection:
    """抖音 frontier-im WebSocket 长连接。"""

    def __init__(self, session: dict[str, Any]):
        self._session = normalize_douyin_session(session)
        self._alive = False
        self._ws: Any = None

    async def listen(self, on_message: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        """连接 WebSocket 并把真实私信推送给业务层；断线重试由 Worker 负责。"""
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("websockets 未安装，无法启动抖音私信监听") from exc

        device_id = str(self._session.get("device_id", ""))
        if not device_id:
            raise RuntimeError("抖音登录态缺少 IM device_id，请重新扫码绑定账号")

        settings = get_settings()
        access_key = compute_access_key(
            device_id,
            app_key=settings.douyin_im_app_key,
            fpid=settings.douyin_im_fpid,
            suffix=settings.douyin_im_access_key_suffix,
        )
        query = urlencode(
            {
                "aid": settings.douyin_im_aid,
                "device_platform": "douyin_pc",
                "fpid": settings.douyin_im_fpid,
                "device_id": device_id,
                "token": self._session["sessionid"],
                "access_key": access_key,
            }
        )

        self._alive = True
        logger.info("[DouyinIM] connecting websocket")
        try:
            async with websockets.connect(
                f"{IM_WS_URL}?{query}",
                additional_headers={"Cookie": self._session["cookie_str"], "User-Agent": USER_AGENT},
                origin=cast(Any, DOUYIN_ORIGIN),
                subprotocols=cast(Any, ["binary", "base64", "pbbp2"]),
                ping_interval=30,
                ping_timeout=10,
                close_timeout=5,
            ) as ws:
                self._ws = ws
                logger.info("[DouyinIM] websocket connected")
                async for raw in ws:
                    if not self._alive:
                        break
                    parsed = self._decode_frame(raw)
                    if parsed:
                        await on_message(parsed)
        finally:
            self._alive = False
            self._ws = None

    def _decode_frame(self, raw: bytes | str) -> dict[str, Any] | None:
        """解析 PushFrame → Response → new_message_notify.message。"""
        if isinstance(raw, str):
            return None
        try:
            frame = Live_pb2.PushFrame()  # type: ignore[attr-defined]
            frame.ParseFromString(raw)
            if frame.payloadType != "pb" or not frame.payload:
                return None

            response = Response_pb2.Response()  # type: ignore[attr-defined]
            response.ParseFromString(frame.payload)
            if response.body.WhichOneof("body") != "new_message_notify":
                return None

            message = response.body.new_message_notify.message
            if not message.sender or not message.conversation_id:
                return None

            content = message.content
            if message.message_type == 7:
                decoded_content = json.loads(message.content)
                content = str(decoded_content.get("text", ""))

            return {
                "remote_uid": str(message.sender),
                "remote_nickname": "",
                "remote_avatar": "",
                "msg_type": int(message.message_type),
                "content": content,
                "dy_conversation_id": message.conversation_id,
                "dy_conversation_short_id": str(message.conversation_short_id),
                "dy_ticket": "",
                "remote_message_id": str(message.server_message_id),
                "remote_index": int(message.index_in_conversation),
            }
        except (DecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning("[DouyinIM] invalid protobuf frame: %s", exc)
            return None

    async def close(self) -> None:
        self._alive = False
        if self._ws:
            await self._ws.close()
        logger.info("[DouyinIM] websocket closed")

    @property
    def is_alive(self) -> bool:
        return self._alive


class DouyinIMProvider:
    """WebSocket 接收实时消息，浏览器复用扫码登录态同步与回复。"""

    name = "douyin_im"
    platform = "douyin"

    def __init__(self, browser_client: DouyinBrowserIMClient | None = None) -> None:
        self._browser_client = browser_client or DouyinBrowserIMClient()

    async def connect(self, session: dict[str, Any]) -> DouyinIMConnection:
        return DouyinIMConnection(session)

    async def send_message(
        self,
        session: dict[str, Any],
        conversation_id: str,
        conversation_short_id: str,
        ticket: str,
        content: str,
        remote_uid: str = "",
        remote_nickname: str = "",
    ) -> bool:
        """通过已登录的抖音网页发送，只有页面确认输入框清空才返回成功。"""
        try:
            return await self._browser_client.send_message(session, remote_uid, remote_nickname, content)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[DouyinIM] browser send failed: %s", exc)
            return False

    async def sync_messages(self, session: dict[str, Any], limit: int = 100) -> list[dict[str, Any]]:
        return await self._browser_client.sync_messages(session, limit)

    async def create_conversation(self, session: dict[str, Any], to_uid: int) -> dict[str, str]:
        """创建会话同样依赖未采集的 web_protect 签名。"""
        normalize_douyin_session(session)
        logger.warning("[DouyinIM] create conversation is unavailable: Douyin web_protect signature is missing")
        return {"conversation_id": "", "conversation_short_id": "", "ticket": ""}
