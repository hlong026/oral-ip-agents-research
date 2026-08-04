from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


root = Path(__file__).resolve().parents[1]
config = root / "server/app/core/config.py"
storage = root / "server/app/core/storage.py"
main = root / "server/app/main.py"
env_dev = root / "server/.env.example"
env_prod = root / "server/.env.production.example"
runtime_tests = root / "server/tests/test_runtime_guards.py"

replace_once(config, "from functools import lru_cache\n", "from functools import lru_cache\nimport re\n")
replace_once(
    config,
    '    s3_bucket: str = "oral-media"\n',
    '''    s3_bucket: str = "oral-media"\n    s3_region: str = "us-east-1"\n    s3_addressing_style: str = "virtual"\n    s3_signature_version: str = "s3"\n    s3_max_pool_connections: int = 32\n    s3_connect_timeout_seconds: float = 5.0\n    s3_read_timeout_seconds: float = 60.0\n    s3_max_attempts: int = 4\n    s3_multipart_threshold_mb: int = 64\n    s3_multipart_chunksize_mb: int = 16\n''',
)
replace_once(
    config,
    '''    if not has_url_host(settings.s3_endpoint, {"http", "https"}) or is_placeholder(settings.s3_endpoint):\n        errors.append("S3_ENDPOINT 必须是有效的非占位地址")\n    if is_placeholder(settings.s3_access_key):\n''',
    '''    s3_url = urlparse(settings.s3_endpoint)\n    if not has_url_host(settings.s3_endpoint, {"https"}) or is_placeholder(settings.s3_endpoint):\n        errors.append("S3_ENDPOINT 生产环境必须是有效的 HTTPS 非占位地址")\n    elif not is_public_dns_hostname(s3_url.hostname):\n        errors.append("S3_ENDPOINT 生产环境不得使用 localhost、IP 或内网保留域名")\n    if not re.fullmatch(r"[a-z]{2,3}-[a-z0-9-]+", settings.s3_region.strip()):\n        errors.append("S3_REGION 必须是有效地域，例如 ap-guangzhou")\n    if settings.s3_addressing_style != "virtual":\n        errors.append("S3_ADDRESSING_STYLE 生产环境必须为 virtual")\n    if settings.s3_signature_version not in {"s3", "s3v4"}:\n        errors.append("S3_SIGNATURE_VERSION 仅支持 s3 或 s3v4")\n    if settings.s3_max_pool_connections < 1:\n        errors.append("S3_MAX_POOL_CONNECTIONS 必须大于 0")\n    if settings.s3_connect_timeout_seconds <= 0 or settings.s3_read_timeout_seconds <= 0:\n        errors.append("S3 连接与读取超时必须大于 0")\n    if settings.s3_max_attempts < 1:\n        errors.append("S3_MAX_ATTEMPTS 必须大于 0")\n    if settings.s3_multipart_threshold_mb < 5 or settings.s3_multipart_chunksize_mb < 5:\n        errors.append("S3 Multipart 阈值和分片大小不得小于 5MB")\n    if s3_url.hostname and s3_url.hostname.endswith(".myqcloud.com"):\n        expected_host = f"cos.{settings.s3_region}.myqcloud.com"\n        if s3_url.hostname != expected_host:\n            errors.append("腾讯云 COS Endpoint 必须与 S3_REGION 一致")\n        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,49}-\\d{5,}", settings.s3_bucket):\n            errors.append("腾讯云 COS 的 S3_BUCKET 必须使用 BucketName-APPID 完整名称")\n    if is_placeholder(settings.s3_access_key):\n''',
)

replace_once(storage, "from urllib.parse import quote\n", "from urllib.parse import quote, urlparse\n")
replace_once(storage, "import aiofiles\n", "import aiofiles\nfrom boto3.s3.transfer import TransferConfig\n")
replace_once(
    storage,
    '''def _s3_client():\n    import boto3\n\n    return boto3.client(\n        "s3",\n        endpoint_url=settings.s3_endpoint,\n        aws_access_key_id=settings.s3_access_key,\n        aws_secret_access_key=settings.s3_secret_key,\n        config=Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 2}),\n    )\n''',
    '''def _s3_client():\n    import boto3\n\n    return boto3.client(\n        "s3",\n        endpoint_url=settings.s3_endpoint.rstrip("/"),\n        region_name=settings.s3_region or None,\n        aws_access_key_id=settings.s3_access_key,\n        aws_secret_access_key=settings.s3_secret_key,\n        config=Config(\n            signature_version=settings.s3_signature_version,\n            s3={"addressing_style": settings.s3_addressing_style},\n            connect_timeout=settings.s3_connect_timeout_seconds,\n            read_timeout=settings.s3_read_timeout_seconds,\n            max_pool_connections=settings.s3_max_pool_connections,\n            retries={"max_attempts": settings.s3_max_attempts, "mode": "standard"},\n        ),\n    )\n\n\ndef _s3_transfer_config() -> TransferConfig:\n    mebibyte = 1024 * 1024\n    return TransferConfig(\n        multipart_threshold=settings.s3_multipart_threshold_mb * mebibyte,\n        multipart_chunksize=settings.s3_multipart_chunksize_mb * mebibyte,\n        max_concurrency=max(1, min(settings.s3_max_pool_connections, 8)),\n        use_threads=True,\n    )\n''',
)
replace_once(
    storage,
    '            await asyncio.to_thread(client.upload_file, str(path), settings.s3_bucket, key)\n',
    '''            await asyncio.to_thread(\n                client.upload_file,\n                str(path),\n                settings.s3_bucket,\n                key,\n                Config=_s3_transfer_config(),\n            )\n''',
)
replace_once(
    storage,
    '        await asyncio.to_thread(client.download_file, settings.s3_bucket, key, str(target))\n',
    '''        await asyncio.to_thread(\n            client.download_file,\n            settings.s3_bucket,\n            key,\n            str(target),\n            Config=_s3_transfer_config(),\n        )\n''',
)
replace_once(
    storage,
    '''async def storage_ready() -> bool:\n    """检查当前存储后端是否可用，不创建探针对象。"""\n    if settings.storage_driver == "local":\n        path = Path(settings.local_storage_dir)\n        return await asyncio.to_thread(lambda: path.is_dir() and os.access(path, os.R_OK | os.W_OK))\n    try:\n        client = _s3_client()\n        await asyncio.to_thread(client.head_bucket, Bucket=settings.s3_bucket)\n        return True\n    except Exception:\n        return False\n''',
    '''async def storage_readiness() -> dict[str, object]:\n    """返回不含密钥的对象存储就绪诊断，供 /readyz 和运维告警使用。"""\n    if settings.storage_driver == "local":\n        path = Path(settings.local_storage_dir)\n        ok = await asyncio.to_thread(lambda: path.is_dir() and os.access(path, os.R_OK | os.W_OK))\n        return {\n            "ok": ok,\n            "driver": "local",\n            "code": "READY" if ok else "LOCAL_STORAGE_UNAVAILABLE",\n        }\n\n    endpoint_host = urlparse(settings.s3_endpoint).hostname or ""\n    base: dict[str, object] = {\n        "driver": "s3",\n        "endpointHost": endpoint_host,\n        "region": settings.s3_region,\n        "bucket": settings.s3_bucket,\n        "addressingStyle": settings.s3_addressing_style,\n        "signatureVersion": settings.s3_signature_version,\n    }\n    try:\n        client = _s3_client()\n        await asyncio.to_thread(client.head_bucket, Bucket=settings.s3_bucket)\n        return {**base, "ok": True, "code": "READY"}\n    except ClientError as exc:\n        error = exc.response.get("Error", {})\n        error_code = str(error.get("Code") or "S3_CLIENT_ERROR")\n        status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")\n        normalized = (\n            "ACCESS_DENIED"\n            if status_code == 403 or error_code in {"403", "AccessDenied"}\n            else "BUCKET_NOT_FOUND"\n            if status_code == 404 or error_code in {"404", "NoSuchBucket", "NotFound"}\n            else "S3_CLIENT_ERROR"\n        )\n        return {**base, "ok": False, "code": normalized, "providerCode": error_code}\n    except Exception as exc:  # noqa: BLE001\n        return {**base, "ok": False, "code": "S3_UNAVAILABLE", "errorType": type(exc).__name__}\n\n\nasync def storage_ready() -> bool:\n    return bool((await storage_readiness()).get("ok"))\n''',
)

replace_once(
    main,
    '''    database_ok, redis_ok, storage_ok = await asyncio.gather(\n        database_ready(),\n        redis_ready(),\n        storage.storage_ready(),\n    )\n''',
    '''    database_ok, redis_ok, storage_status = await asyncio.gather(\n        database_ready(),\n        redis_ready(),\n        storage.storage_readiness(),\n    )\n    storage_ok = bool(storage_status.get("ok"))\n''',
)
replace_once(
    main,
    '        "storage": {"ok": storage_ok, "required": True},\n',
    '        "storage": {**storage_status, "required": True},\n',
)

for env_path in (env_dev, env_prod):
    replace_once(
        env_path,
        "S3_BUCKET=oral-media\n",
        '''S3_BUCKET=oral-media\nS3_REGION=us-east-1\nS3_ADDRESSING_STYLE=virtual\nS3_SIGNATURE_VERSION=s3\nS3_MAX_POOL_CONNECTIONS=32\nS3_CONNECT_TIMEOUT_SECONDS=5\nS3_READ_TIMEOUT_SECONDS=60\nS3_MAX_ATTEMPTS=4\nS3_MULTIPART_THRESHOLD_MB=64\nS3_MULTIPART_CHUNKSIZE_MB=16\n''',
    )

prod_text = env_prod.read_text(encoding="utf-8")
prod_text = prod_text.replace(
    "# 对象存储（生产建议 s3/MinIO；MEDIA_PUBLIC_BASE_URL 必须公网可达，云端 ASR 依赖回源下载）\nSTORAGE_DRIVER=s3\nS3_ENDPOINT=https://minio.example.com\nS3_ACCESS_KEY=REPLACE_S3_ACCESS_KEY\nS3_SECRET_KEY=REPLACE_WITH_32BYTES_S3_SECRET_KEY\nS3_BUCKET=oral-media\nS3_REGION=us-east-1\n",
    "# 腾讯云 COS（Bucket 使用 BucketName-APPID 完整名称；Endpoint 不包含 Bucket）\nSTORAGE_DRIVER=s3\nS3_ENDPOINT=https://cos.ap-guangzhou.myqcloud.com\nS3_ACCESS_KEY=REPLACE_WITH_CAM_SECRET_ID\nS3_SECRET_KEY=REPLACE_WITH_32BYTES_CAM_SECRET_KEY\nS3_BUCKET=oral-media-1250000000\nS3_REGION=ap-guangzhou\n",
)
env_prod.write_text(prod_text, encoding="utf-8")

replace_once(
    runtime_tests,
    '''        "s3_endpoint": "https://minio.oral.company",\n        "s3_access_key": "production-access-key",\n        "s3_secret_key": "f" * 32,\n        "s3_bucket": "oral-media",\n''',
    '''        "s3_endpoint": "https://cos.ap-guangzhou.myqcloud.com",\n        "s3_access_key": "production-access-key",\n        "s3_secret_key": "f" * 32,\n        "s3_bucket": "oral-media-1250000000",\n        "s3_region": "ap-guangzhou",\n        "s3_addressing_style": "virtual",\n        "s3_signature_version": "s3",\n''',
)
replace_once(
    runtime_tests,
    '''        ({"s3_endpoint": ""}, "S3_ENDPOINT"),\n        ({"s3_endpoint": "https://"}, "S3_ENDPOINT"),\n''',
    '''        ({"s3_endpoint": ""}, "S3_ENDPOINT"),\n        ({"s3_endpoint": "https://"}, "S3_ENDPOINT"),\n        ({"s3_endpoint": "http://cos.ap-guangzhou.myqcloud.com"}, "S3_ENDPOINT"),\n        ({"s3_endpoint": "https://localhost:9000"}, "S3_ENDPOINT"),\n        ({"s3_region": ""}, "S3_REGION"),\n        ({"s3_addressing_style": "path"}, "S3_ADDRESSING_STYLE"),\n        ({"s3_signature_version": "v2-custom"}, "S3_SIGNATURE_VERSION"),\n        ({"s3_bucket": "oral-media"}, "BucketName-APPID"),\n        ({"s3_endpoint": "https://cos.ap-beijing.myqcloud.com"}, "Endpoint"),\n''',
)

(root / "server/tests/test_cos_storage_adapter.py").write_text(
    '''"""Tencent COS S3 compatibility and readiness diagnostics."""\n\nimport sys\nfrom types import SimpleNamespace\n\nfrom botocore.exceptions import ClientError\n\n\ndef test_s3_client_uses_cos_compatibility_settings(monkeypatch) -> None:\n    from app.core import storage\n\n    captured: dict[str, object] = {}\n\n    def fake_client(service: str, **kwargs: object) -> object:\n        captured.update(service=service, **kwargs)\n        return object()\n\n    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=fake_client))\n    monkeypatch.setattr(storage.settings, "s3_endpoint", "https://cos.ap-guangzhou.myqcloud.com")\n    monkeypatch.setattr(storage.settings, "s3_region", "ap-guangzhou")\n    monkeypatch.setattr(storage.settings, "s3_addressing_style", "virtual")\n    monkeypatch.setattr(storage.settings, "s3_signature_version", "s3")\n    monkeypatch.setattr(storage.settings, "s3_max_pool_connections", 48)\n    monkeypatch.setattr(storage.settings, "s3_connect_timeout_seconds", 7.0)\n    monkeypatch.setattr(storage.settings, "s3_read_timeout_seconds", 70.0)\n    monkeypatch.setattr(storage.settings, "s3_max_attempts", 5)\n\n    storage._s3_client()\n\n    assert captured["service"] == "s3"\n    assert captured["endpoint_url"] == "https://cos.ap-guangzhou.myqcloud.com"\n    assert captured["region_name"] == "ap-guangzhou"\n    config = captured["config"]\n    assert config.signature_version == "s3"\n    assert config.s3 == {"addressing_style": "virtual"}\n    assert config.max_pool_connections == 48\n    assert config.connect_timeout == 7.0\n    assert config.read_timeout == 70.0\n    assert config.retries["max_attempts"] == 5\n\n\ndef test_transfer_config_enables_multipart(monkeypatch) -> None:\n    from app.core import storage\n\n    monkeypatch.setattr(storage.settings, "s3_multipart_threshold_mb", 32)\n    monkeypatch.setattr(storage.settings, "s3_multipart_chunksize_mb", 8)\n    monkeypatch.setattr(storage.settings, "s3_max_pool_connections", 4)\n\n    config = storage._s3_transfer_config()\n\n    assert config.multipart_threshold == 32 * 1024 * 1024\n    assert config.multipart_chunksize == 8 * 1024 * 1024\n    assert config.max_request_concurrency == 4\n\n\nasync def test_storage_readiness_reports_cos_access_denied(monkeypatch) -> None:\n    from app.core import storage\n\n    class DeniedClient:\n        def head_bucket(self, **_kwargs: object) -> None:\n            raise ClientError(\n                {\n                    "Error": {"Code": "AccessDenied"},\n                    "ResponseMetadata": {"HTTPStatusCode": 403},\n                },\n                "HeadBucket",\n            )\n\n    monkeypatch.setattr(storage.settings, "storage_driver", "s3")\n    monkeypatch.setattr(storage.settings, "s3_endpoint", "https://cos.ap-guangzhou.myqcloud.com")\n    monkeypatch.setattr(storage.settings, "s3_region", "ap-guangzhou")\n    monkeypatch.setattr(storage.settings, "s3_bucket", "oral-media-1250000000")\n    monkeypatch.setattr(storage, "_s3_client", lambda: DeniedClient())\n\n    result = await storage.storage_readiness()\n\n    assert result["ok"] is False\n    assert result["code"] == "ACCESS_DENIED"\n    assert result["providerCode"] == "AccessDenied"\n    assert "access" not in str(result).lower() or "access_key" not in str(result).lower()\n\n\nasync def test_storage_readiness_reports_bucket_not_found(monkeypatch) -> None:\n    from app.core import storage\n\n    class MissingClient:\n        def head_bucket(self, **_kwargs: object) -> None:\n            raise ClientError(\n                {\n                    "Error": {"Code": "NoSuchBucket"},\n                    "ResponseMetadata": {"HTTPStatusCode": 404},\n                },\n                "HeadBucket",\n            )\n\n    monkeypatch.setattr(storage.settings, "storage_driver", "s3")\n    monkeypatch.setattr(storage.settings, "s3_endpoint", "https://cos.ap-guangzhou.myqcloud.com")\n    monkeypatch.setattr(storage.settings, "s3_region", "ap-guangzhou")\n    monkeypatch.setattr(storage.settings, "s3_bucket", "oral-media-1250000000")\n    monkeypatch.setattr(storage, "_s3_client", lambda: MissingClient())\n\n    result = await storage.storage_readiness()\n\n    assert result["ok"] is False\n    assert result["code"] == "BUCKET_NOT_FOUND"\n''',
    encoding="utf-8",
)
