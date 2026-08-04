"""对象存储：local（MVP 默认）/ s3（MinIO）；产物落库用相对 key，访问走 /media 路由"""

import asyncio
import hashlib
import hmac
import os
import tempfile
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath
from typing import Protocol
from urllib.parse import quote

import aiofiles
from botocore.config import Config
from botocore.exceptions import ClientError

from .config import get_settings

settings = get_settings()


class StorageConfigurationError(RuntimeError):
    """存储配置不足以支持真实外部调用。"""


class UploadTooLarge(ValueError):
    """上传流超过业务上限。"""


class AsyncUploadStream(Protocol):
    async def read(self, size: int = -1) -> bytes: ...


def _validated_key(key: str) -> str:
    path = PurePosixPath(key)
    if not key or path.is_absolute() or ".." in path.parts:
        raise ValueError("非法媒体 key")
    return path.as_posix()


def _key(prefix: str, filename: str) -> str:
    suffix = Path(filename).suffix or ""
    return _validated_key(f"{prefix}/{uuid.uuid4().hex[:12]}{suffix}")


def _s3_client():
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        config=Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 2}),
    )


def _is_missing_object_error(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}


async def save_bytes(prefix: str, filename: str, data: bytes) -> str:
    """保存字节流，返回存储 key"""
    key = _key(prefix, filename)
    if settings.storage_driver == "local":
        path = Path(settings.local_storage_dir) / key
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, "wb") as f:
            await f.write(data)
        return key
    # S3 驱动（生产）
    client = _s3_client()
    await asyncio.to_thread(client.put_object, Bucket=settings.s3_bucket, Key=key, Body=data)
    return key


async def save_text(prefix: str, filename: str, text: str) -> str:
    return await save_bytes(prefix, filename, text.encode("utf-8"))


async def read_limited(source: AsyncUploadStream, max_bytes: int, chunk_size: int = 1024 * 1024) -> bytes:
    """分块读取小型上传；最多读取 limit+1 字节后立即拒绝。"""
    chunks: list[bytes] = []
    total = 0
    while True:
        data = await source.read(min(chunk_size, max_bytes - total + 1))
        if not data:
            return b"".join(chunks)
        total += len(data)
        if total > max_bytes:
            raise UploadTooLarge
        chunks.append(data)


async def save_stream(
    prefix: str,
    filename: str,
    source: AsyncUploadStream,
    *,
    max_bytes: int,
    chunk_size: int = 1024 * 1024,
) -> tuple[str, int]:
    """分块保存大文件，避免把整个上传载入进程内存。"""
    key = _key(prefix, filename)
    path = local_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        async with aiofiles.open(path, "wb") as target:
            while True:
                data = await source.read(min(chunk_size, max_bytes - total + 1))
                if not data:
                    break
                total += len(data)
                if total > max_bytes:
                    raise UploadTooLarge
                await target.write(data)
        if settings.storage_driver == "s3":
            client = _s3_client()
            await asyncio.to_thread(client.upload_file, str(path), settings.s3_bucket, key)
            await asyncio.to_thread(path.unlink, missing_ok=True)
        return key, total
    except BaseException:
        await asyncio.to_thread(path.unlink, missing_ok=True)
        raise


async def delete(key: str) -> None:
    key = _validated_key(key)
    if settings.storage_driver == "local":
        await asyncio.to_thread(local_path(key).unlink, missing_ok=True)
        return
    client = _s3_client()
    await asyncio.to_thread(client.delete_object, Bucket=settings.s3_bucket, Key=key)


def local_path(key: str) -> Path:
    return Path(settings.local_storage_dir) / _validated_key(key)


async def exists(key: str) -> bool:
    """媒体文件是否仍存在。S3 驱动必须真查 head_object：默认返回存在会让
    CLEAN_MASTER_MISSING 之类的源文件校验在生产上失效。"""
    key = _validated_key(key)
    if settings.storage_driver == "local":
        return local_path(key).exists()

    client = _s3_client()
    try:
        await asyncio.to_thread(client.head_object, Bucket=settings.s3_bucket, Key=key)
        return True
    except ClientError as exc:
        if _is_missing_object_error(exc):
            return False
        raise


async def read_bytes(key: str) -> bytes:
    key = _validated_key(key)
    if settings.storage_driver == "local":
        async with aiofiles.open(local_path(key), "rb") as f:
            return await f.read()

    client = _s3_client()
    try:
        obj = await asyncio.to_thread(client.get_object, Bucket=settings.s3_bucket, Key=key)
        return await asyncio.to_thread(obj["Body"].read)
    except ClientError as exc:
        if _is_missing_object_error(exc):
            raise FileNotFoundError(key) from exc
        raise


async def download_to_path(key: str, target: Path) -> None:
    """Download an S3 object to disk without buffering the complete object in memory."""
    key = _validated_key(key)
    if settings.storage_driver == "local":
        raise StorageConfigurationError("local storage does not require download_to_path")
    target.parent.mkdir(parents=True, exist_ok=True)
    client = _s3_client()
    try:
        await asyncio.to_thread(client.download_file, settings.s3_bucket, key, str(target))
    except ClientError as exc:
        if _is_missing_object_error(exc):
            raise FileNotFoundError(key) from exc
        raise
    await asyncio.to_thread(target.chmod, 0o600)


@asynccontextmanager
async def materialized_path(key: str, *, name: str = "media") -> AsyncIterator[Path]:
    """Provide a local path and clean temporary S3 downloads on context exit."""
    key = _validated_key(key)
    if settings.storage_driver == "local":
        yield local_path(key)
        return

    with tempfile.TemporaryDirectory(prefix="oral-media-") as directory:
        temp_dir = Path(directory)
        await asyncio.to_thread(temp_dir.chmod, 0o700)
        suffix = Path(key).suffix or ".bin"
        target = temp_dir / f"{name}{suffix}"
        await download_to_path(key, target)
        yield target


async def size(key: str) -> int:
    """媒体文件字节数（Range 响应需要），不存在时抛 FileNotFoundError"""
    key = _validated_key(key)
    if settings.storage_driver == "local":
        stat = await asyncio.to_thread(local_path(key).stat)
        return stat.st_size

    client = _s3_client()
    try:
        head = await asyncio.to_thread(client.head_object, Bucket=settings.s3_bucket, Key=key)
        return int(head["ContentLength"])
    except ClientError as exc:
        if _is_missing_object_error(exc):
            raise FileNotFoundError(key) from exc
        raise


async def stream_range(key: str, start: int, end: int, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
    """流式读取 [start, end] 闭区间字节段，避免大视频整段进内存"""
    key = _validated_key(key)
    if settings.storage_driver == "local":
        async with aiofiles.open(local_path(key), "rb") as f:
            await f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                data = await f.read(min(chunk_size, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data
        return

    client = _s3_client()
    try:
        obj = await asyncio.to_thread(
            client.get_object, Bucket=settings.s3_bucket, Key=key, Range=f"bytes={start}-{end}"
        )
    except ClientError as exc:
        if _is_missing_object_error(exc):
            raise FileNotFoundError(key) from exc
        raise
    body = obj["Body"]
    while True:
        data = await asyncio.to_thread(body.read, chunk_size)
        if not data:
            break
        yield data


def _media_signature(key: str, expires_at: int) -> str:
    message = f"{_validated_key(key)}:{expires_at}".encode()
    return hmac.new(settings.app_secret.encode(), message, hashlib.sha256).hexdigest()


def signed_media_path(key: str, *, expires_in: int = 3600) -> str:
    """生成短期媒体访问路径；签名本身是 bearer，不在日志中附带用户凭据。"""
    key = _validated_key(key)
    expires_at = int(time.time()) + expires_in
    signature = _media_signature(key, expires_at)
    return f"/media/{quote(key, safe='/')}?exp={expires_at}&sig={signature}"


def verify_media_signature(key: str, expires_at: str | None, signature: str | None) -> bool:
    if not expires_at or not signature:
        return False
    try:
        expires = int(expires_at)
    except ValueError:
        return False
    if expires < int(time.time()):
        return False
    try:
        expected = _media_signature(key, expires)
    except ValueError:
        return False
    return hmac.compare_digest(expected, signature)


async def get_accessible_url(
    key: str,
    *,
    require_public: bool = False,
    expires_in: int = 24 * 60 * 60,
) -> str:
    """返回云端 Provider 可下载的媒体 URL。"""
    key = _validated_key(key)
    base_url = settings.media_public_base_url.strip().rstrip("/")
    if require_public and not base_url:
        raise StorageConfigurationError(
            "真实云端转写前必须配置 MEDIA_PUBLIC_BASE_URL，并确保其 /media 路径可从公网访问"
        )
    base_url = base_url or "http://127.0.0.1:8000"
    return f"{base_url}{signed_media_path(key, expires_in=expires_in)}"


async def storage_ready() -> bool:
    """检查当前存储后端是否可用，不创建探针对象。"""
    if settings.storage_driver == "local":
        path = Path(settings.local_storage_dir)
        return await asyncio.to_thread(lambda: path.is_dir() and os.access(path, os.R_OK | os.W_OK))
    try:
        client = _s3_client()
        await asyncio.to_thread(client.head_bucket, Bucket=settings.s3_bucket)
        return True
    except Exception:
        return False
