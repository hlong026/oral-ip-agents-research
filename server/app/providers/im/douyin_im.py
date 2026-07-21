"""抖音 IM Provider（整合 DouYin_Spider 的 WebSocket + Protobuf 逻辑）
- connect(): 建立 wss://frontier-im.douyin.com/ws/v2 长连接
- send_message()/create_conversation(): 缺少固定 Request protobuf + 签名测试证据时 fail-closed
"""

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast
from urllib.parse import urlencode

from google.protobuf.message import DecodeError

from app.core.config import get_settings
from app.providers.im.proto.v1 import live_pb2, response_pb2

logger = logging.getLogger(__name__)

# 抖音 IM 常量
IM_WS_URL = "wss://frontier-im.douyin.com/ws/v2"
DOUYIN_ORIGIN = "https://www.douyin.com"
DOUYIN_IM_DEVICE_STORAGE_KEY = "oral_im_device_id"
DOUYIN_IM_SUBPROTOCOLS = ["binary", "base64", "pbbp2"]

COMMON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.douyin.com/",
    "Origin": "https://www.douyin.com",
}


class DouyinIMError(RuntimeError):
    """Base error for explicit Douyin IM failure mapping."""


class DouyinIMSessionError(DouyinIMError):
    """The saved login state cannot be used for IM."""


class DouyinIMConfigError(DouyinIMError):
    """Required Douyin IM settings are missing."""


class DouyinIMUnsupportedError(DouyinIMError):
    """Protocol evidence is insufficient, so the operation must fail closed."""


class DouyinIMNetworkError(DouyinIMError):
    """Network failure while calling Douyin IM endpoints."""


def _get_im_constants() -> tuple[str, str, str]:
    """#11 从配置读取 IM 常量"""
    s = get_settings()
    return s.douyin_im_app_key, s.douyin_im_aid, s.douyin_im_fpid


def _parse_cookie_string(cookie_str: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for part in cookie_str.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name:
            cookies[name] = value
    return cookies


def _cookie_domain_matches_douyin(domain: str) -> bool:
    normalized = domain.lstrip(".").lower()
    return normalized == "douyin.com" or normalized.endswith(".douyin.com")


def _device_id_from_storage_state(session: dict[str, Any]) -> str:
    for origin in session.get("origins", []):
        if not isinstance(origin, dict) or origin.get("origin") != DOUYIN_ORIGIN:
            continue
        for item in origin.get("localStorage", []):
            if isinstance(item, dict) and item.get("name") == DOUYIN_IM_DEVICE_STORAGE_KEY:
                return str(item.get("value") or "").strip()
    return ""


def normalize_douyin_session(session: dict[str, Any]) -> dict[str, Any]:
    """Normalize Playwright storage_state into the cookie/device contract used by frontier-im."""
    normalized = dict(session)
    cookie_map = _parse_cookie_string(str(session.get("cookie_str") or ""))

    for cookie in session.get("cookies", []):
        if not isinstance(cookie, dict):
            continue
        name = str(cookie.get("name") or "")
        value = str(cookie.get("value") or "")
        domain = str(cookie.get("domain") or "")
        if name and _cookie_domain_matches_douyin(domain):
            cookie_map[name] = value

    session_id = str(session.get("sessionid") or cookie_map.get("sessionid") or cookie_map.get("sessionid_ss") or "")
    if not session_id:
        raise DouyinIMSessionError("抖音登录态缺少 sessionid，请重新扫码绑定账号")

    device_id = str(session.get("device_id") or _device_id_from_storage_state(session) or "").strip()
    if not device_id:
        raise DouyinIMSessionError("抖音登录态缺少真实 IM device_id，请重新扫码绑定账号")

    normalized["sessionid"] = session_id
    normalized["device_id"] = device_id
    normalized["cookie_str"] = "; ".join(f"{name}={value}" for name, value in cookie_map.items())
    return normalized


def compute_access_key(device_id: str) -> str:
    """DouYin_Spider formula: md5(fpid + appKey + deviceId + configured suffix)."""
    app_key, _aid, fpid = _get_im_constants()
    suffix = get_settings().douyin_im_access_key_suffix
    if not app_key:
        raise DouyinIMConfigError("缺少 DOUYIN_IM_APP_KEY，无法计算抖音 IM access_key")
    if not suffix:
        raise DouyinIMConfigError("缺少 DOUYIN_IM_ACCESS_KEY_SUFFIX，无法计算抖音 IM access_key")
    raw = fpid + app_key + device_id + suffix
    return hashlib.md5(raw.encode()).hexdigest()


def _compute_access_key(device_id: str, _session_id: str = "") -> str:
    return compute_access_key(device_id)


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
        except ImportError as exc:
            raise DouyinIMError("websockets 未安装，无法启动抖音 IM 监听") from exc

        self._session = normalize_douyin_session(self._session)
        cookie_str = self._session["cookie_str"]
        session_id = self._session["sessionid"]
        device_id = self._session["device_id"]

        access_key = _compute_access_key(device_id)
        _app_key, aid, fpid = _get_im_constants()
        query = urlencode(
            {
                "aid": aid,
                "device_platform": "douyin_pc",
                "fpid": fpid,
                "device_id": device_id,
                "token": session_id,
                "access_key": access_key,
            }
        )
        ws_url = f"{IM_WS_URL}?{query}"

        self._alive = True
        logger.info(f"[DouyinIM] connecting ws device_id={device_id[:8]}...")

        try:
            async with websockets.connect(
                ws_url,
                additional_headers={**COMMON_HEADERS, "Cookie": cookie_str},
                origin=cast(Any, DOUYIN_ORIGIN),
                subprotocols=cast(Any, DOUYIN_IM_SUBPROTOCOLS),
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
        except DouyinIMError:
            raise
        except Exception as exc:
            raise DouyinIMNetworkError(f"抖音 IM WebSocket 连接失败: {exc}") from exc
        finally:
            self._alive = False
            self._ws = None

    def _decode_frame(self, raw: bytes | str) -> dict[str, Any] | None:
        """Decode the fixed v1 PushFrame → Response → message contract."""
        if isinstance(raw, str):
            return None
        try:
            frame = live_pb2.PushFrame()  # type: ignore[attr-defined]
            frame.ParseFromString(raw)
            if frame.payloadType != "pb" or not frame.payload:
                return None

            response = response_pb2.Response()  # type: ignore[attr-defined]
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

    async def _fetch_device_id(self, cookie_str: str) -> str:
        """Random device IDs are forbidden; QR login must persist the real browser device_id."""
        raise DouyinIMSessionError("抖音登录态缺少真实 IM device_id，请重新扫码绑定账号")

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
        """Fail closed until the fixed send Request protobuf and signature are captured and tested."""
        normalize_douyin_session(session)
        raise DouyinIMUnsupportedError("抖音 IM 发送缺少固定 Request protobuf + 签名测试证据，已按 fail-closed 拒绝")

    async def create_conversation(self, session: dict[str, Any], to_uid: int) -> dict[str, str]:
        """Fail closed until the fixed create-conversation request contract is captured and tested."""
        normalize_douyin_session(session)
        raise DouyinIMUnsupportedError("抖音 IM 建会话缺少固定 Request protobuf + 签名测试证据，已按 fail-closed 拒绝")
