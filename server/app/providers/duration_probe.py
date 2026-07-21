"""用供应商明确时长或 ffprobe 验证媒体时长。"""

import asyncio
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger("oral.providers.duration_probe")


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
    """返回供应商明确时长或 ffprobe 读取的真实时长。"""
    del platform
    if known_duration is not None and known_duration > 0:
        logger.debug("使用供应商返回时长: %.1fs", known_duration)
        return known_duration

    if not video_url or not video_url.startswith(("http://", "https://")):
        return None

    try:
        process = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            video_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=20)
        except TimeoutError:
            process.kill()
            await process.communicate()
            logger.error("ffprobe 探测链接媒体超时")
            return None
    except FileNotFoundError:
        logger.error("ffprobe 不可用，无法验证链接媒体时长")
        return None

    if process.returncode != 0:
        return None
    try:
        duration = float(stdout.decode().strip())
    except ValueError:
        return None
    return duration if duration > 0 else None
