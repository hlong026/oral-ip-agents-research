"""
Douyidou 视频解析 Provider（抖音/小红书/快手等多平台去水印 + 文案提取）
- 网关：https://gateway.diadi.cn/api/parse
- 鉴权：MD5 签名（排序参数 + appSecret）
- 响应：{code:0, data:{type, video[], images[], audio[], cover, text, platform, author, ...}}
"""
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.dynamic_config import get_config

from .base import ParseResult, StepRecoverableError

logger = logging.getLogger("oral.providers.douyidou")


def _is_retryable(exc: BaseException) -> bool:
    """仅对网络错误和 5xx 重试，4xx（认证失败等）不重试"""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.HTTPError)

# Douyidou 平台编号映射
PLATFORM_MAP: dict[int, str] = {
    1: "douyin",
    2: "kuaishou",
    3: "xiaohongshu",
    4: "bilibili",
    5: "weibo",
    9: "other",
}


@dataclass
class DouyidouParseResult:
    """Douyidou 完整解析结果（扩展 ParseResult，携带文案/封面等额外信息）"""
    platform: str
    title: str
    video_url: str | None = None       # 视频直链（公网可访问）
    video_key: str | None = None       # 兼容 ParseResult（此处直接存URL）
    text: str | None = None            # 已有文案（非空时可跳过ASR）
    cover: str | None = None           # 封面URL
    author: dict[str, Any] = field(default_factory=dict)
    media_type: str = ""               # video / images / audio
    images: list[str] = field(default_factory=list)
    audio: list[str] = field(default_factory=list)
    duration_sec: float | None = None  # 视频时长(秒)，用于ASR分流决策
    degraded: bool = False
    raw_platform_id: int = 0


class DouyidouParser:
    """Douyidou 多平台视频解析（主解析通道，凭据从前端设置页动态读取）"""

    name = "douyidou"

    async def _get_credentials(self) -> tuple[str, str, str]:
        """动态读取凭据（app_id, app_secret, base_url）"""
        app_id = await get_config("douyidou_app_id")
        app_secret = await get_config("douyidou_app_secret")
        base_url = await get_config("douyidou_base_url", "https://gateway.diadi.cn")
        return app_id, app_secret, base_url.rstrip("/")

    def _sign(self, params: dict[str, str], app_secret: str) -> str:
        """MD5签名：参数按key排序 → k=v& 拼接 → 末尾追加 appSecret → MD5"""
        sorted_keys = sorted(params.keys())
        parts = [f"{k}={quote(str(params[k]))}" for k in sorted_keys]
        pre_str = "&".join(parts) + app_secret
        return hashlib.md5(pre_str.encode()).hexdigest()

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(min=1, max=5),
        retry=retry_if_exception(_is_retryable),
    )
    async def _request(self, url: str, is_title: int = 0) -> dict[str, Any]:
        """调用 Douyidou 解析接口"""
        app_id, app_secret, base_url = await self._get_credentials()
        params: dict[str, str] = {
            "url": url,
            "app_id": app_id,
        }
        if is_title:
            params["is_title"] = str(is_title)

        sign = self._sign(params, app_secret)

        # 构造排序后的查询字符串
        sorted_keys = sorted(params.keys())
        query_parts = [f"{k}={quote(str(params[k]))}" for k in sorted_keys]
        query_string = "&".join(query_parts)
        full_url = f"{base_url}/api/parse?{query_string}"

        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            resp = await client.get(full_url, headers={"Sign": sign})
            resp.raise_for_status()
            return resp.json()

    async def parse_url(self, url: str) -> ParseResult:
        """实现 ParseProvider Protocol（兼容降级链）"""
        result = await self.parse_url_full(url)
        return ParseResult(
            platform=result.platform,
            title=result.title,
            video_key=result.video_url,  # 直接用视频URL作为key传给ASR
            degraded=False,
        )

    async def parse_url_full(self, url: str, is_title: int = 0) -> DouyidouParseResult:
        """
        完整解析：返回视频直链 + 文案 + 封面 + 作者等全部信息。
        
        核心逻辑：
        - text 非空 → 已有文案，可跳过 ASR
        - video 非空 → 视频直链，可传给 ASR 转写
        """
        app_id, app_secret, _ = await self._get_credentials()
        if not app_id or not app_secret:
            raise StepRecoverableError("Douyidou app_id/app_secret 未配置，请在设置页填写")

        try:
            data = await self._request(url, is_title)
        except httpx.HTTPError as e:
            raise StepRecoverableError(f"Douyidou 请求失败: {e}") from e

        # 校验响应
        code = data.get("code")
        if code != 0:
            msg = data.get("message", "未知错误")
            raise StepRecoverableError(f"Douyidou 解析失败(code={code}): {msg}")

        payload = data.get("data", {})
        if not payload:
            raise StepRecoverableError("Douyidou 返回数据为空")

        # 提取字段
        platform_id = payload.get("platform", 0)
        platform_name = PLATFORM_MAP.get(platform_id, f"platform_{platform_id}")
        video_list = payload.get("video") or []
        video_url = video_list[0] if video_list else None
        text = payload.get("text") or None
        title = payload.get("title") or ""
        cover = payload.get("cover") or None
        author = payload.get("author") or {}
        media_type = payload.get("type") or ""
        images = payload.get("images") or []
        audio_list = payload.get("audio") or []

        # 提取时长（Douyidou 可能返回 duration / video_duration / time 字段，单位秒或毫秒）
        duration_sec = self._extract_duration(payload)

        # 如果无标题但有文案，取文案前20字作标题
        if not title and text:
            title = text[:20] + ("..." if len(text) > 20 else "")

        logger.info(
            f"Douyidou 解析成功: platform={platform_name}, type={media_type}, "
            f"has_video={bool(video_url)}, has_text={bool(text)}, duration={duration_sec}"
        )

        return DouyidouParseResult(
            platform=platform_name,
            title=title,
            video_url=video_url,
            video_key=video_url,
            text=text,
            cover=cover,
            author=author if isinstance(author, dict) else {},
            media_type=media_type,
            images=images if isinstance(images, list) else [],
            audio=audio_list if isinstance(audio_list, list) else [],
            duration_sec=duration_sec,
            degraded=False,
            raw_platform_id=platform_id,
        )

    @staticmethod
    def _extract_duration(payload: dict[str, Any]) -> float | None:
        """
        从 Douyidou 响应中提取视频时长(秒)。
        兼容多种字段名和单位（秒/毫秒）。
        """
        # 尝试常见字段名
        for key in ("duration", "video_duration", "time", "length"):
            val = payload.get(key)
            if val is not None:
                try:
                    num = float(val)
                    # 如果值 > 10000，大概率是毫秒，转为秒
                    return num / 1000.0 if num > 10000 else num
                except (ValueError, TypeError):
                    continue
        # 尝试嵌套在 video_info 中
        video_info = payload.get("video_info") or {}
        if isinstance(video_info, dict):
            for key in ("duration", "time"):
                val = video_info.get(key)
                if val is not None:
                    try:
                        num = float(val)
                        return num / 1000.0 if num > 10000 else num
                    except (ValueError, TypeError):
                        continue
        return None
