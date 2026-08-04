"""用 ffprobe/FFmpeg 校验成片是否满足发布最低要求。"""

import asyncio
import json
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.storage import exists, local_path, read_bytes

settings = get_settings()


class MediaQualityError(RuntimeError):
    """媒体无法探测或不满足发布质量门禁。"""


@dataclass
class MediaQualityReport:
    passed: bool
    duration: float
    videoCodec: str
    audioCodec: str
    width: int
    height: int
    sizeBytes: int
    meanVolumeDb: float | None
    errors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def inspect_media(
    media_key: str,
    *,
    require_audio: bool,
    expected_width: int | None = None,
    expected_height: int | None = None,
) -> MediaQualityReport:
    """探测媒体并在不合格时抛错，防止坏产物进入发布队列。"""
    with tempfile.TemporaryDirectory(prefix="oral-quality-") as directory:
        source = await _materialize(media_key, Path(directory))
        probe = await _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                source,
            ],
            limit_seconds=30,
        )
        try:
            payload = json.loads(probe)
        except json.JSONDecodeError as exc:
            raise MediaQualityError("ffprobe 未返回有效 JSON") from exc

        streams: list[dict[str, Any]] = payload.get("streams") or []
        video: dict[str, Any] = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
        audio: dict[str, Any] = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
        format_info = payload.get("format") or {}
        duration = _number(format_info.get("duration"))
        width = int(video.get("width") or 0)
        height = int(video.get("height") or 0)
        size_bytes = int(_number(format_info.get("size")))
        video_codec = str(video.get("codec_name") or "")
        audio_codec = str(audio.get("codec_name") or "")
        errors: list[str] = []

        if duration <= 0:
            errors.append("无法验证视频时长")
        if video_codec != "h264":
            errors.append(f"视频编码必须为 h264，当前为 {video_codec or 'missing'}")
        if require_audio and audio_codec != "aac":
            errors.append(f"音频编码必须为 aac，当前为 {audio_codec or 'missing'}")
        if expected_width and width != expected_width:
            errors.append(f"视频宽度应为 {expected_width}，当前为 {width}")
        if expected_height and height != expected_height:
            errors.append(f"视频高度应为 {expected_height}，当前为 {height}")
        if size_bytes <= 1_000:
            errors.append("视频文件为空或过小")

        mean_volume = await _mean_volume(source) if audio_codec else None
        if require_audio and mean_volume is None:
            errors.append("无法验证音轨音量")
        elif mean_volume is not None and mean_volume <= -60:
            errors.append("音轨接近静音")

        report = MediaQualityReport(
            passed=not errors,
            duration=duration,
            videoCodec=video_codec,
            audioCodec=audio_codec,
            width=width,
            height=height,
            sizeBytes=size_bytes,
            meanVolumeDb=mean_volume,
            errors=errors,
        )
        if errors:
            raise MediaQualityError("；".join(errors))
        return report


async def _materialize(media_key: str, directory: Path) -> str:
    if media_key.startswith(("http://", "https://")):
        return media_key
    if settings.storage_driver == "local" and await exists(media_key):
        return str(local_path(media_key))
    try:
        data = await read_bytes(media_key)
    except (FileNotFoundError, OSError) as exc:
        raise MediaQualityError("媒体文件不存在") from exc
    path = directory / (Path(media_key).name or "media.bin")
    await asyncio.to_thread(path.write_bytes, data)
    return str(path)


async def _run(command: list[str], *, limit_seconds: float) -> str:
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=limit_seconds)
    except FileNotFoundError as exc:
        raise MediaQualityError(f"{command[0]} 不可用") from exc
    except TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise MediaQualityError(f"{command[0]} 执行超时") from exc
    if process.returncode != 0:
        error = stderr.decode("utf-8", errors="replace").strip()
        raise MediaQualityError(f"{command[0]} 探测失败: {error[-300:]}")
    return stdout.decode("utf-8", errors="replace")


async def _mean_volume(source: str) -> float | None:
    try:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-v",
            "info",
            "-i",
            source,
            "-map",
            "0:a:0",
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except (FileNotFoundError, TimeoutError):
        return None
    if process.returncode != 0:
        return None
    match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", stderr.decode("utf-8", errors="replace"))
    return float(match.group(1)) if match else None


def _number(value: object) -> float:
    try:
        return float(str(value or 0))
    except (TypeError, ValueError):
        return 0.0
