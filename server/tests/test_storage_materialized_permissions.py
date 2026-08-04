"""Private file permissions for S3 media materialization."""

import asyncio
import stat
from pathlib import Path


async def test_s3_materialized_path_uses_private_directory_and_file(monkeypatch) -> None:
    from app.core import storage

    class FakeS3Client:
        def download_file(self, bucket: str, key: str, filename: str) -> None:
            assert bucket == "test-bucket"
            assert key == "videos/private.mp4"
            Path(filename).write_bytes(b"private-media")

    monkeypatch.setattr(storage.settings, "storage_driver", "s3")
    monkeypatch.setattr(storage.settings, "s3_bucket", "test-bucket")
    monkeypatch.setattr(storage, "_s3_client", lambda: FakeS3Client())

    async with storage.materialized_path("videos/private.mp4", name="video") as path:
        materialized = path
        file_stat = await asyncio.to_thread(path.stat)
        parent_stat = await asyncio.to_thread(path.parent.stat)
        assert stat.S_IMODE(file_stat.st_mode) == 0o600
        assert stat.S_IMODE(parent_stat.st_mode) == 0o700
        assert await asyncio.to_thread(path.read_bytes) == b"private-media"

    assert not await asyncio.to_thread(materialized.exists)
