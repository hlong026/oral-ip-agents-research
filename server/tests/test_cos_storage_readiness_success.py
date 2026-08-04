"""Positive Tencent COS readiness contract."""


async def test_storage_readiness_reports_safe_cos_identity(monkeypatch) -> None:
    from app.core import storage

    class ReadyClient:
        def head_bucket(self, **kwargs: object) -> None:
            assert kwargs == {"Bucket": "oral-media-1250000000"}

    monkeypatch.setattr(storage.settings, "storage_driver", "s3")
    monkeypatch.setattr(storage.settings, "s3_endpoint", "https://cos.ap-guangzhou.myqcloud.com")
    monkeypatch.setattr(storage.settings, "s3_region", "ap-guangzhou")
    monkeypatch.setattr(storage.settings, "s3_bucket", "oral-media-1250000000")
    monkeypatch.setattr(storage.settings, "s3_addressing_style", "virtual")
    monkeypatch.setattr(storage.settings, "s3_signature_version", "s3")
    monkeypatch.setattr(storage, "_s3_client", lambda: ReadyClient())

    result = await storage.storage_readiness()

    assert result == {
        "driver": "s3",
        "endpointHost": "cos.ap-guangzhou.myqcloud.com",
        "region": "ap-guangzhou",
        "bucket": "oral-media-1250000000",
        "addressingStyle": "virtual",
        "signatureVersion": "s3",
        "ok": True,
        "code": "READY",
    }
    assert "secret" not in str(result).lower()
