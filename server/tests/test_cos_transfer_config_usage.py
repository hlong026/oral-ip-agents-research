"""Tencent COS upload and download must use the shared TransferConfig."""

from pathlib import Path


class _AsyncSource:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.sent = False

    async def read(self, _size: int = -1) -> bytes:
        if self.sent:
            return b""
        self.sent = True
        return self.payload


async def test_cos_upload_and_download_share_transfer_config(tmp_path, monkeypatch) -> None:
    from app.core import storage

    transfer = object()
    calls: list[tuple[str, object]] = []

    class FakeClient:
        def upload_file(
            self,
            filename: str,
            bucket: str,
            key: str,
            *,
            Config: object,
        ) -> None:
            assert Path(filename).read_bytes() == b"upload-bytes"
            assert bucket == "oral-media-1250000000"
            assert key.startswith("migration-test/")
            calls.append(("upload", Config))

        def download_file(
            self,
            bucket: str,
            key: str,
            filename: str,
            *,
            Config: object,
        ) -> None:
            assert bucket == "oral-media-1250000000"
            assert key == "videos/example.mp4"
            Path(filename).write_bytes(b"download-bytes")
            calls.append(("download", Config))

    monkeypatch.setattr(storage.settings, "storage_driver", "s3")
    monkeypatch.setattr(storage.settings, "local_storage_dir", str(tmp_path / "storage"))
    monkeypatch.setattr(storage.settings, "s3_bucket", "oral-media-1250000000")
    monkeypatch.setattr(storage, "_s3_client", lambda: FakeClient())
    monkeypatch.setattr(storage, "_s3_transfer_config", lambda: transfer)

    await storage.save_stream(
        "migration-test",
        "sample.bin",
        _AsyncSource(b"upload-bytes"),
        max_bytes=1024,
    )
    target = tmp_path / "download.mp4"
    await storage.download_to_path("videos/example.mp4", target)

    assert target.read_bytes() == b"download-bytes"
    assert calls == [("upload", transfer), ("download", transfer)]
