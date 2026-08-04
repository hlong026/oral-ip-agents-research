"""Tencent COS S3 compatibility and readiness diagnostics."""

import sys
from types import SimpleNamespace

from botocore.exceptions import ClientError


def test_s3_client_uses_cos_compatibility_settings(monkeypatch) -> None:
    from app.core import storage

    captured: dict[str, object] = {}

    def fake_client(service: str, **kwargs: object) -> object:
        captured.update(service=service, **kwargs)
        return object()

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=fake_client))
    monkeypatch.setattr(storage.settings, "s3_endpoint", "https://cos.ap-guangzhou.myqcloud.com")
    monkeypatch.setattr(storage.settings, "s3_region", "ap-guangzhou")
    monkeypatch.setattr(storage.settings, "s3_addressing_style", "virtual")
    monkeypatch.setattr(storage.settings, "s3_signature_version", "s3")
    monkeypatch.setattr(storage.settings, "s3_max_pool_connections", 48)
    monkeypatch.setattr(storage.settings, "s3_connect_timeout_seconds", 7.0)
    monkeypatch.setattr(storage.settings, "s3_read_timeout_seconds", 70.0)
    monkeypatch.setattr(storage.settings, "s3_max_attempts", 5)

    storage._s3_client()

    assert captured["service"] == "s3"
    assert captured["endpoint_url"] == "https://cos.ap-guangzhou.myqcloud.com"
    assert captured["region_name"] == "ap-guangzhou"
    config = captured["config"]
    assert config.signature_version == "s3"
    assert config.s3 == {"addressing_style": "virtual"}
    assert config.max_pool_connections == 48
    assert config.connect_timeout == 7.0
    assert config.read_timeout == 70.0
    assert config.retries["max_attempts"] == 5


def test_transfer_config_enables_multipart(monkeypatch) -> None:
    from app.core import storage

    monkeypatch.setattr(storage.settings, "s3_multipart_threshold_mb", 32)
    monkeypatch.setattr(storage.settings, "s3_multipart_chunksize_mb", 8)
    monkeypatch.setattr(storage.settings, "s3_max_pool_connections", 4)

    config = storage._s3_transfer_config()

    assert config.multipart_threshold == 32 * 1024 * 1024
    assert config.multipart_chunksize == 8 * 1024 * 1024
    assert config.max_request_concurrency == 4


async def test_storage_readiness_reports_cos_access_denied(monkeypatch) -> None:
    from app.core import storage

    class DeniedClient:
        def head_bucket(self, **_kwargs: object) -> None:
            raise ClientError(
                {
                    "Error": {"Code": "AccessDenied"},
                    "ResponseMetadata": {"HTTPStatusCode": 403},
                },
                "HeadBucket",
            )

    monkeypatch.setattr(storage.settings, "storage_driver", "s3")
    monkeypatch.setattr(storage.settings, "s3_endpoint", "https://cos.ap-guangzhou.myqcloud.com")
    monkeypatch.setattr(storage.settings, "s3_region", "ap-guangzhou")
    monkeypatch.setattr(storage.settings, "s3_bucket", "oral-media-1250000000")
    monkeypatch.setattr(storage, "_s3_client", lambda: DeniedClient())

    result = await storage.storage_readiness()

    assert result["ok"] is False
    assert result["code"] == "ACCESS_DENIED"
    assert result["providerCode"] == "AccessDenied"
    assert "access" not in str(result).lower() or "access_key" not in str(result).lower()


async def test_storage_readiness_reports_bucket_not_found(monkeypatch) -> None:
    from app.core import storage

    class MissingClient:
        def head_bucket(self, **_kwargs: object) -> None:
            raise ClientError(
                {
                    "Error": {"Code": "NoSuchBucket"},
                    "ResponseMetadata": {"HTTPStatusCode": 404},
                },
                "HeadBucket",
            )

    monkeypatch.setattr(storage.settings, "storage_driver", "s3")
    monkeypatch.setattr(storage.settings, "s3_endpoint", "https://cos.ap-guangzhou.myqcloud.com")
    monkeypatch.setattr(storage.settings, "s3_region", "ap-guangzhou")
    monkeypatch.setattr(storage.settings, "s3_bucket", "oral-media-1250000000")
    monkeypatch.setattr(storage, "_s3_client", lambda: MissingClient())

    result = await storage.storage_readiness()

    assert result["ok"] is False
    assert result["code"] == "BUCKET_NOT_FOUND"
