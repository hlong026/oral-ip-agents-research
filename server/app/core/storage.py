"""对象存储：local（MVP 默认）/ s3（MinIO）；产物落库用相对 key，访问走 /media 路由"""

import uuid
from pathlib import Path

import aiofiles

from .config import get_settings

settings = get_settings()


def _key(prefix: str, filename: str) -> str:
    suffix = Path(filename).suffix or ""
    return f"{prefix}/{uuid.uuid4().hex[:12]}{suffix}"


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
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
    )
    client.put_object(Bucket=settings.s3_bucket, Key=key, Body=data)
    return key


async def save_text(prefix: str, filename: str, text: str) -> str:
    return await save_bytes(prefix, filename, text.encode("utf-8"))


def local_path(key: str) -> Path:
    return Path(settings.local_storage_dir) / key


def exists(key: str) -> bool:
    if settings.storage_driver == "local":
        return local_path(key).exists()
    return True


async def read_bytes(key: str) -> bytes:
    if settings.storage_driver == "local":
        async with aiofiles.open(local_path(key), "rb") as f:
            return await f.read()
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
    )
    obj = client.get_object(Bucket=settings.s3_bucket, Key=key)
    return obj["Body"].read()
