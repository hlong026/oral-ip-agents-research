"""Tencent COS endpoint normalization."""

import sys
from types import SimpleNamespace


def test_s3_client_strips_trailing_endpoint_slashes(monkeypatch) -> None:
    from app.core import storage

    captured: dict[str, object] = {}

    def fake_client(service: str, **kwargs: object) -> object:
        captured.update(service=service, **kwargs)
        return object()

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=fake_client))
    monkeypatch.setattr(
        storage.settings,
        "s3_endpoint",
        "https://cos.ap-guangzhou.myqcloud.com///",
    )
    monkeypatch.setattr(storage.settings, "s3_region", "ap-guangzhou")

    storage._s3_client()

    assert captured["endpoint_url"] == "https://cos.ap-guangzhou.myqcloud.com"
