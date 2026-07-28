"""
飞影数字人 API V2 Provider 实现（内部代号 hifly，用户侧白标不暴露）
- HiFlyClient: 基础 HTTP 客户端（Bearer Token + 文件上传 + 错误码映射）
- HiFlyVoice: 声音克隆 + TTS（VoiceProvider 实现）
- HiFlyAvatar: 数字人形象克隆 + 视频创作（AvatarProvider 实现）
- 凭据从前端设置页动态读取（dynamic_config），保存即时生效无需重启
"""

import asyncio
import logging
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.dynamic_config import get_config
from app.core.storage import read_bytes, save_bytes
from app.providers.duration_probe import probe_media_bytes

from .base import ProviderError, ProviderOutcomeUnknown, StepRecoverableError, SynthesizeResult, WordTs

logger = logging.getLogger(__name__)
settings = get_settings()

# 飞影错误码 → 用户友好提示（白标：不暴露供应商名）
ERROR_MESSAGES: dict[int, str] = {
    11: "参数不正确，请检查输入",
    14: "找不到资源",
    1001: "当前任务排队中，请稍后重试",
    1002: "服务额度不足，请联系管理员",
    1005: "服务暂不可用，请联系管理员",
    1006: "服务等级不够，请联系管理员",
    1009: "声音资源已售罄",
    1011: "声音样本不符合要求，请更换音频",
    1013: "声音数量已达上限",
    1015: "提交的作品数量达到上限，请稍后重试",
    2003: "服务认证失败",
    2011: "文件大小超出限制",
    2012: "文件格式不支持，请上传 mp3/m4a/wav",
    2013: "素材获取失败，请重新上传",
    2014: "素材获取失败，请重新上传",
    2015: "数字人训练失败，请检查素材质量后重试",
    2016: "素材获取失败，请重新上传",
}


class HiFlyAPIError(ProviderError):
    """飞影 API 业务错误（含用户友好消息）"""

    def __init__(self, code: int, message: str = ""):
        self.code = code
        self.user_message = ERROR_MESSAGES.get(code, message or "服务暂时不可用，请稍后重试")
        super().__init__(self.user_message)


class HiFlyClient:
    """飞影 API 基础 HTTP 客户端（凭据动态读取，变更时自动重建连接）"""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._client_config: tuple[str, str] | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        """动态获取 HTTP 客户端（凭据变更时自动重建）"""
        token = await get_config("feiying_api_key")
        base_url = await get_config("feiying_base_url", "https://hfw-api.hifly.cc")
        if not token:
            raise StepRecoverableError("声音/数字人服务未配置，请在设置页填写 API Key")
        client_config = (token, base_url)
        if self._client is None or self._client_config != client_config:
            if self._client:
                await self._client.aclose()
            self._client = httpx.AsyncClient(
                base_url=base_url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=httpx.Timeout(60.0),
            )
            self._client_config = client_config
        return self._client

    @property
    async def available(self) -> bool:
        token = await get_config("feiying_api_key")
        return bool(token)

    async def request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        """安全查询可重试一次；创建类请求结果未知时停止自动重试和降级。"""
        method_upper = method.upper()
        safe_to_retry = method_upper in {"GET", "HEAD", "OPTIONS"}
        attempts = 2 if safe_to_retry else 1
        data: dict[str, Any] | None = None

        for attempt in range(attempts):
            client = await self._ensure_client()
            try:
                resp = await client.request(method_upper, path, **kwargs)
                resp.raise_for_status()
                payload = resp.json()
                if not isinstance(payload, dict):
                    raise ValueError("响应不是 JSON 对象")
                data = payload
                break
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if status_code == 401:
                    raise StepRecoverableError("服务认证失败，触发降级") from exc
                if not safe_to_retry and (status_code == 429 or status_code >= 500):
                    raise ProviderOutcomeUnknown(f"服务提交结果未知（HTTP {status_code}），请先对账再重试") from exc
                raise StepRecoverableError(f"服务请求失败: {status_code}") from exc
            except (httpx.TransportError, ValueError) as exc:
                if not safe_to_retry:
                    raise ProviderOutcomeUnknown("服务提交结果未知，请先对账再重试") from exc
                if attempt + 1 >= attempts:
                    raise StepRecoverableError(f"服务连接失败: {exc}") from exc
                await asyncio.sleep(1)

        if data is None:
            raise StepRecoverableError("服务未返回有效响应")

        code = data.get("code", 0)
        if code != 0:
            if code == 2003:
                raise StepRecoverableError("服务认证失败，触发降级")
            raise HiFlyAPIError(code, data.get("message", ""))
        return data

    async def upload_file(self, file_key: str, extension: str) -> str:
        """上传本地存储文件到飞影 OSS，返回 file_id"""
        # 1. 获取上传地址
        data = await self.request("POST", "/api/v2/hifly/tool/create_upload_url", json={"file_extension": extension})
        upload_url = data["upload_url"]
        content_type = data["content_type"]
        file_id = data["file_id"]

        # 2. 读取文件并 PUT 上传
        file_data = await read_bytes(file_key)
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as upload_client:
            resp = await upload_client.put(
                upload_url,
                content=file_data,
                headers={"Content-Type": content_type},
            )
            if resp.status_code not in (200, 201):
                raise StepRecoverableError(f"文件上传失败: {resp.status_code}")
        return file_id

    async def upload_bytes(self, file_data: bytes, extension: str, content_type: str | None = None) -> str:
        """直接上传字节流到飞影 OSS，返回 file_id"""
        data = await self.request("POST", "/api/v2/hifly/tool/create_upload_url", json={"file_extension": extension})
        upload_url = data["upload_url"]
        ct = content_type or data["content_type"]
        file_id = data["file_id"]

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as upload_client:
            resp = await upload_client.put(
                upload_url,
                content=file_data,
                headers={"Content-Type": ct},
            )
            if resp.status_code not in (200, 201):
                raise StepRecoverableError(f"文件上传失败: {resp.status_code}")
        return file_id

    async def download_to_storage(self, url: str, prefix: str, filename: str) -> str:
        """下载远程文件转存到自有存储，返回存储 key（白标：不暴露供应商临时链接）"""
        if not url.startswith(("http://", "https://")):
            raise StepRecoverableError("供应商未返回有效下载地址")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as dl_client:
                resp = await dl_client.get(url)
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise StepRecoverableError(f"产物下载失败: {exc}") from exc
        if not resp.content:
            raise StepRecoverableError("供应商返回的产物为空")
        return await save_bytes(prefix, filename, resp.content)


# 全局单例
_client: HiFlyClient | None = None


def get_client() -> HiFlyClient:
    global _client
    if _client is None:
        _client = HiFlyClient()
    return _client


class HiFlyVoice:
    """飞影声音克隆 + TTS（VoiceProvider 实现，内部标识不暴露给用户）"""

    name = "hifly-voice"

    def __init__(self) -> None:
        self._c = get_client()

    async def clone(self, name: str, sample_key: str, consent_token: str, language: str = "zh") -> str:
        """
        声音克隆：上传音频样本 → 创建克隆任务 → 返回 task_id
        音频要求：mp3/m4a/wav，≤20MB，5s~3min
        """
        # 推断扩展名
        ext = Path(sample_key).suffix.lstrip(".") or "mp3"
        file_id = await self._c.upload_file(sample_key, ext)

        payload: dict[str, Any] = {
            "title": name[:20],
            "voice_type": 8,
            "file_id": file_id,
        }
        if language and language != "zh":
            payload["languages"] = language

        data = await self._c.request("POST", "/api/v2/hifly/voice/create", json=payload)
        task_id = data.get("task_id", "")
        logger.info(f"[hifly] voice clone task created: {task_id}")
        return task_id

    async def query_clone_task(self, task_id: str) -> dict[str, Any]:
        """
        查询声音克隆任务状态
        返回: {status: int, voice_id: str, demo_url: str}
        status: 1等待 2处理 3完成 4失败
        """
        data = await self._c.request("GET", "/api/v2/hifly/voice/task", params={"task_id": task_id})
        return {
            "status": data.get("status", 1),
            "voice_id": data.get("voice", ""),
            "demo_url": data.get("demo_url", ""),
        }

    async def synthesize(self, voice_id: str, text: str, speed: float = 1.0) -> SynthesizeResult:
        """
        TTS 合成：文本 → 音频文件
        使用 audio/create_by_tts 接口，轮询获取结果
        """
        payload: dict[str, Any] = {
            "voice": voice_id,
            "text": text[:10000],
            "title": "TTS合成",
        }
        data = await self._c.request("POST", "/api/v2/hifly/audio/create_by_tts", json=payload)
        task_id = data.get("task_id", "")
        if not task_id:
            raise StepRecoverableError("TTS 未返回 task_id")

        # 轮询任务完成
        result = await self._poll_video_task(task_id)
        audio_url = result.get("audio_url") or result.get("video_Url") or result.get("video_url") or ""
        duration = float(result.get("duration", 0) or 0)

        # 下载音频转存
        if not audio_url:
            raise StepRecoverableError("TTS 完成但未返回音频地址")
        audio_key = await self._c.download_to_storage(audio_url, "tts", "audio.mp3")
        probed_duration = await probe_media_bytes(await read_bytes(audio_key), ".mp3")
        duration = probed_duration or duration
        if duration <= 0:
            raise StepRecoverableError("TTS 音频时长无法验证")

        # 生成字级时间戳（均匀分布）
        words: list[WordTs] = []
        if text and duration > 0:
            per_char = duration / max(len(text), 1)
            t = 0.0
            for ch in text:
                if ch.strip():
                    words.append(WordTs(word=ch, start=round(t, 2), end=round(t + per_char, 2)))
                    t += per_char

        return SynthesizeResult(audio_key=audio_key, words=words, duration=duration)

    async def edit_params(self, voice_id: str, rate: str, volume: str, pitch: str) -> None:
        """修改声音参数（语速/音量/语调）"""
        await self._c.request(
            "POST",
            "/api/v2/hifly/voice/edit",
            json={
                "voice": voice_id,
                "rate": rate,
                "volume": volume,
                "pitch": pitch,
            },
        )

    async def list_voices(self) -> list[dict[str, Any]]:
        """查询已克隆的声音列表（仅自己的）：单页上限 300，翻页聚合避免超量声音丢失"""
        items: list[dict[str, Any]] = []
        size = 300
        for page in range(1, 21):  # 安全上限 20 页，防御异常响应导致死循环
            data = await self._c.request(
                "GET", "/api/v2/hifly/voice/list", params={"page": page, "size": size, "kind": 1}
            )
            batch = data.get("data", []) or []
            items.extend(batch)
            if len(batch) < size:
                break
        return items

    async def _poll_video_task(self, task_id: str) -> dict[str, Any]:
        """轮询创作任务状态直到完成"""
        interval = settings.feiying_poll_interval
        max_attempts = settings.feiying_poll_max_attempts
        for _ in range(max_attempts):
            data = await self._c.request("GET", "/api/v2/hifly/video/task", params={"task_id": task_id})
            status = data.get("status", 1)
            if status == 3:
                return data
            if status == 4:
                raise HiFlyAPIError(2015, "音频合成失败")
            await asyncio.sleep(interval)
        raise StepRecoverableError("音频合成超时")


class HiFlyAvatar:
    """飞影数字人形象克隆 + 视频创作（AvatarProvider 实现，内部标识不暴露）"""

    name = "hifly-avatar"

    def __init__(self) -> None:
        self._c = get_client()

    async def clone_by_video(self, name: str, video_key: str, consent_token: str) -> str:
        """
        视频数字人克隆：上传视频 → 创建克隆任务 → 返回 task_id
        视频要求：mp4/mov, h264/hevc, 360p~4K, 5s~30min, ≤500MB
        """
        ext = Path(video_key).suffix.lstrip(".") or "mp4"
        file_id = await self._c.upload_file(video_key, ext)

        data = await self._c.request(
            "POST",
            "/api/v2/hifly/avatar/create_by_video",
            json={
                "title": name[:20],
                "file_id": file_id,
            },
        )
        task_id = data.get("task_id", "")
        logger.info(f"[hifly] avatar clone_by_video task: {task_id}")
        return task_id

    async def clone_by_image(self, name: str, image_key: str, model: int = 2) -> str:
        """
        图片数字人克隆：上传图片 → 创建克隆任务 → 返回 task_id
        model: 1=视频2.0, 2=视频2.1（默认）
        """
        ext = Path(image_key).suffix.lstrip(".") or "jpg"
        file_id = await self._c.upload_file(image_key, ext)

        data = await self._c.request(
            "POST",
            "/api/v2/hifly/avatar/create_by_image",
            json={
                "title": name[:20],
                "file_id": file_id,
                "model": model,
            },
        )
        task_id = data.get("task_id", "")
        logger.info(f"[hifly] avatar clone_by_image task: {task_id}")
        return task_id

    async def query_avatar_task(self, task_id: str) -> dict[str, Any]:
        """
        查询数字人克隆任务状态
        返回: {status: int, avatar_id: str}
        status: 1等待 2处理 3完成 4失败
        """
        data = await self._c.request("GET", "/api/v2/hifly/avatar/task", params={"task_id": task_id})
        return {
            "status": data.get("status", 1),
            "avatar_id": data.get("avatar", ""),
        }

    async def create_by_audio(self, avatar_id: str, audio_key: str) -> str:
        """
        视频创作（音频驱动）：上传音频 + 指定数字人 → 返回 task_id
        """
        ext = Path(audio_key).suffix.lstrip(".") or "mp3"
        file_id = await self._c.upload_file(audio_key, ext)

        data = await self._c.request(
            "POST",
            "/api/v2/hifly/video/create_by_audio",
            json={
                "file_id": file_id,
                "avatar": avatar_id,
                "title": "口播视频",
            },
        )
        task_id = data.get("task_id", "")
        if not task_id:
            raise StepRecoverableError("数字人任务未返回 task_id")
        logger.info(f"[hifly] video create_by_audio task: {task_id}")
        return task_id

    async def create_by_tts(
        self, avatar_id: str, voice_id: str, text: str, subtitle_opts: dict[str, Any] | None = None
    ) -> str:
        """
        视频创作（文本驱动）：文本 + 声音 + 数字人 → 视频（含字幕）
        """
        payload: dict[str, Any] = {
            "voice": voice_id,
            "text": text[:10000],
            "avatar": avatar_id,
            "title": "口播视频",
        }
        if subtitle_opts:
            payload.update(subtitle_opts)

        data = await self._c.request("POST", "/api/v2/hifly/video/create_by_tts", json=payload)
        task_id = data.get("task_id", "")
        logger.info(f"[hifly] video create_by_tts task: {task_id}")
        return task_id

    async def query_video_task(self, task_id: str) -> dict[str, Any]:
        """
        查询创作任务状态（单次查询，不含轮询）
        返回: {status, video_url, duration}
        """
        data = await self._c.request("GET", "/api/v2/hifly/video/task", params={"task_id": task_id})
        return {
            "status": data.get("status", 1),
            "video_url": data.get("video_Url", ""),
            "duration": data.get("duration", 0),
        }

    async def poll_video_task(self, task_id: str) -> dict[str, Any]:
        """轮询创作任务直到完成，返回 {video_url, duration}"""
        interval = settings.feiying_poll_interval
        max_attempts = settings.feiying_poll_max_attempts
        for _ in range(max_attempts):
            result = await self.query_video_task(task_id)
            if result["status"] == 3:
                if not result.get("video_url"):
                    raise StepRecoverableError("数字人任务完成但未返回视频地址")
                return result
            if result["status"] == 4:
                raise HiFlyAPIError(2015, "视频生成失败")
            await asyncio.sleep(interval)
        raise StepRecoverableError("视频生成超时")

    async def download_video(self, temp_url: str) -> str:
        """下载临时视频 URL 转存到自有存储（白标），返回 video_key"""
        if not temp_url:
            raise StepRecoverableError("数字人任务未返回视频地址")
        return await self._c.download_to_storage(temp_url, "avatar-videos", "video.mp4")

    async def list_public(self) -> list[dict[str, Any]]:
        """查询公共数字人（内部使用，不暴露给用户）"""
        data = await self._c.request("GET", "/api/v2/hifly/avatar/list", params={"page": 1, "size": 100, "kind": 2})
        return data.get("data", [])

    async def get_credit(self) -> int:
        """查询账户积分余额（内部监控）"""
        data = await self._c.request("GET", "/api/v2/hifly/account/credit")
        return data.get("left", 0)
