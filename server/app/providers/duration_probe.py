"""
视频时长探测工具
- 优先使用 API 返回的 duration 字段（DouyidouParseResult.duration_sec）
- 兜底：HEAD 请求获取 Content-Length → 按平台典型码率估算时长
- 用于 ASR 分流决策：≤阈值走 Flash 同步，>阈值走异步轮询
"""
import asyncio
import logging
import tempfile
from pathlib import Path

import httpx

logger = logging.getLogger("oral.providers.duration_probe")

# 各平台典型视频码率（bytes/sec），用于从文件大小估算时长
# 短视频平台一般 720p/1080p，码率 1~4 Mbps
PLATFORM_BITRATE: dict[str, float] = {
    "douyin": 300_000,       # ~2.4 Mbps，抖音默认 720p/1080p
    "kuaishou": 250_000,     # ~2 Mbps
    "xiaohongshu": 250_000,  # ~2 Mbps
    "bilibili": 400_000,     # ~3.2 Mbps，B站码率偏高
    "weibo": 200_000,        # ~1.6 Mbps
}
DEFAULT_BITRATE = 300_000  # 默认 ~2.4 Mbps


async def probe_media_bytes(data: bytes, suffix: str = ".bin") -> float | None:
    """用 ffprobe 读取上传媒体的真实时长；无法验证时返回 None。"""
    if not data:
        return None
    with tempfile.TemporaryDirectory(prefix="oral-duration-") as directory:
        path = Path(directory) / f"upload{suffix or '.bin'}"
        await asyncio.to_thread(path.write_bytes, data)
        try:
            process = await asyncio.create_subprocess_exec(
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=15)
        except (FileNotFoundError, TimeoutError):
            logger.error("ffprobe 不可用或执行超时，无法验证媒体时长")
            return None
        if process.returncode != 0:
            return None
        try:
            duration = float(stdout.decode().strip())
        except ValueError:
            return None
        return duration if duration > 0 else None


async def probe_duration(
    video_url: str,
    platform: str = "",
    known_duration: float | None = None,
) -> float | None:
    """
    探测视频时长(秒)。

    策略：
    1. known_duration 非空 → 直接返回（来自 Douyidou API）
    2. HEAD 请求获取 Content-Length → 按平台码率估算
    3. 全部失败 → 返回 None（ASR 层安全兜底走异步）

    Args:
        video_url: 公网可访问的视频直链
        platform: 平台标识（用于选择估算码率）
        known_duration: 已知时长（API返回），非空时直接返回

    Returns:
        估算时长(秒)，或 None 表示无法判断
    """
    # 策略1：已有确切时长
    if known_duration is not None and known_duration > 0:
        logger.debug(f"使用 API 返回时长: {known_duration:.1f}s")
        return known_duration

    # 策略2：HEAD 请求估算
    if not video_url or not video_url.startswith(("http://", "https://")):
        return None

    try:
        content_length = await _get_content_length(video_url)
        if content_length and content_length > 0:
            bitrate = PLATFORM_BITRATE.get(platform, DEFAULT_BITRATE)
            estimated = content_length / bitrate
            logger.info(
                f"HEAD 估算时长: size={content_length/1024/1024:.1f}MB, "
                f"bitrate={bitrate/1000:.0f}KB/s, estimated={estimated:.1f}s"
            )
            return estimated
    except Exception as e:
        logger.warning(f"HEAD 探测失败（不影响主流程）: {e}")

    return None


async def _get_content_length(url: str) -> int | None:
    """HEAD 请求获取文件大小（Content-Length），不支持 HEAD 时流式 Range GET 避免 OOM"""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            follow_redirects=True,
        ) as client:
            resp = await client.head(url)
            # 某些 CDN 不支持 HEAD，降级为流式 Range GET（仅读 headers，不下载 body）
            if resp.status_code == 405:
                async with client.stream("GET", url, headers={"Range": "bytes=0-0"}) as stream_resp:
                    if stream_resp.status_code == 206:
                        # 从 Content-Range 提取总大小: "bytes 0-0/12345678"
                        content_range = stream_resp.headers.get("content-range", "")
                        if "/" in content_range:
                            total = content_range.split("/")[-1]
                            if total.isdigit():
                                return int(total)
                    elif stream_resp.status_code == 200:
                        # 服务器不支持 Range，尝试从 content-length 取
                        cl = stream_resp.headers.get("content-length")
                        if cl and cl.isdigit():
                            return int(cl)
                    return None

            cl = resp.headers.get("content-length")
            if cl and cl.isdigit():
                return int(cl)
    except httpx.HTTPError:
        pass
    return None
