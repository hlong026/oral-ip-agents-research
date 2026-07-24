"""对象存储：local（MVP 默认）/ s3（MinIO）；产物落库用相对 key，访问走 /media 路由"""

import asyncio
import uuid
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import aiofiles
from botocore.config import Config
from botocore.exceptions import ClientError

from .config import get_settings

settings = get_settings()


class StorageConfigurationError(RuntimeError):
    """存储配置不足以支持真实外部调用。"""


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


def local_path(key: str) -> Path:
    return Path(settings.local_storage_dir) / _validated_key(key)


def exists(key: str) -> bool:
    if settings.storage_driver == "local":
        return local_path(key).exists()
    return True


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
        if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
            raise FileNotFoundError(key) from exc
        raise


async def get_accessible_url(key: str, *, require_public: bool = False) -> str:
    """返回云端 Provider 可下载的媒体 URL。"""
    key = _validated_key(key)
    base_url = settings.media_public_base_url.strip().rstrip("/")
    if require_public and not base_url:
        raise StorageConfigurationError(
            "真实云端转写前必须配置 MEDIA_PUBLIC_BASE_URL，并确保其 /media 路径可从公网访问"
        )
    base_url = base_url or "http://127.0.0.1:8000"
    return f"{base_url}/media/{quote(key, safe='/')}"
