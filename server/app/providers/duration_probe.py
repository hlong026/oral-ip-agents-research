"""用供应商明确时长或 ffprobe 验证媒体时长。"""

import asyncio
import json
import logging
import tempfile
from pathlib import Path

import aiofiles

logger = logging.getLogger("oral.providers.duration_probe")


class MediaProcessingError(RuntimeError):
    """上传媒体无法转换为云端 ASR 可接受的音频。"""


async def _materialize_storage_key(key: str, directory: str) -> Path:
    from app.core import storage

    if storage.settings.storage_driver == "local":
        return storage.local_path(key)
    path = Path(directory) / (Path(key).name or "upload.bin")
    total = await storage.size(key)
    async with aiofiles.open(path, "wb") as target:
        async for chunk in storage.stream_range(key, 0, max(total - 1, 0)):
            await target.write(chunk)
    return path


async def _probe_media_path(path: Path) -> dict | None:
    process: asyncio.subprocess.Process | None = None
    try:
        process = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,format_name:stream=codec_type,codec_name",
            "-of",
            "json",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=15)
    except FileNotFoundError:
        logger.error("ffprobe 不可用或执行超时，无法验证媒体")
        return None
    except TimeoutError:
        if process is not None:
            process.kill()
            await process.communicate()
        logger.error("ffprobe 不可用或执行超时，无法验证媒体")
        return None
    if process.returncode != 0:
        return None
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return None


async def probe_media_key(key: str) -> dict | None:
    """从存储 key 流式物化后读取真实容器、编码和时长。"""
    with tempfile.TemporaryDirectory(prefix="oral-duration-key-") as directory:
        path = await _materialize_storage_key(key, directory)
        return await _probe_media_path(path)


async def extract_audio_key(key: str) -> bytes:
    """从存储中的大媒体直接提取压缩音轨，不把原视频读入内存。"""
    with tempfile.TemporaryDirectory(prefix="oral-asr-key-") as directory:
        source = await _materialize_storage_key(key, directory)
        output = Path(directory) / "audio.mp3"
        try:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(source),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-b:a",
                "64k",
                str(output),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=90)
        except FileNotFoundError as exc:
            raise MediaProcessingError("FFmpeg 未安装或不可执行") from exc
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise MediaProcessingError("提取音轨超时") from exc
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace")[-500:]
            raise MediaProcessingError(f"提取音轨失败(exit={process.returncode}): {detail}")
        audio = await asyncio.to_thread(output.read_bytes)
        if not audio:
            raise MediaProcessingError("未提取到有效音轨")
        return audio


async def extract_audio_bytes(data: bytes, suffix: str) -> bytes:
    """将上传媒体转为单声道 16kHz MP3，避免 Base64 请求超过 Provider 限制。"""
    if not data:
        raise MediaProcessingError("上传媒体为空")
    with tempfile.TemporaryDirectory(prefix="oral-asr-audio-") as directory:
        source = Path(directory) / f"source{suffix or '.bin'}"
        output = Path(directory) / "audio.mp3"
        await asyncio.to_thread(source.write_bytes, data)
        try:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(source),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-b:a",
                "64k",
                str(output),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=90)
        except FileNotFoundError as exc:
            raise MediaProcessingError("FFmpeg 未安装或不可执行") from exc
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise MediaProcessingError("提取音轨超时") from exc
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace")[-500:]
            raise MediaProcessingError(f"提取音轨失败(exit={process.returncode}): {detail}")
        audio = await asyncio.to_thread(output.read_bytes)
        if not audio:
            raise MediaProcessingError("未提取到有效音轨")
        return audio


async def transcode_audio_to_m4a(data: bytes, suffix: str) -> bytes:
    """将浏览器录音等不受支持格式（webm/ogg 等）转码为 m4a，满足供应商 mp3/m4a/wav 要求。"""
    if not data:
        raise MediaProcessingError("上传音频为空")
    with tempfile.TemporaryDirectory(prefix="oral-voice-sample-") as directory:
        source = Path(directory) / f"source{suffix or '.bin'}"
        output = Path(directory) / "sample.m4a"
        await asyncio.to_thread(source.write_bytes, data)
        try:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(source),
                "-vn",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                str(output),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=90)
        except FileNotFoundError as exc:
            raise MediaProcessingError("FFmpeg 未安装或不可执行") from exc
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise MediaProcessingError("音频转码超时") from exc
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace")[-500:]
            raise MediaProcessingError(f"音频转码失败(exit={process.returncode}): {detail}")
        audio = await asyncio.to_thread(output.read_bytes)
        if not audio:
            raise MediaProcessingError("转码后音频为空")
        return audio


async def probe_media_bytes(data: bytes, suffix: str = ".bin") -> float | None:
    """用 ffprobe 读取上传媒体的真实时长；无法验证时返回 None。"""
    info = await probe_media_bytes_info(data, suffix)
    try:
        duration = float((info or {})["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        return None
    return duration if duration > 0 else None


async def probe_media_bytes_info(data: bytes, suffix: str = ".bin") -> dict | None:
    """读取内存中小型媒体的真实容器、编码和时长。"""
    if not data:
        return None
    with tempfile.TemporaryDirectory(prefix="oral-duration-") as directory:
        path = Path(directory) / f"upload{suffix or '.bin'}"
        await asyncio.to_thread(path.write_bytes, data)
        return await _probe_media_path(path)


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
