"""Media delivery must behave the same for local and S3-backed storage."""

from pathlib import Path

from botocore.exceptions import ClientError
from httpx import AsyncClient


async def test_local_media_is_served_from_storage(client: AsyncClient, tmp_path: Path, monkeypatch) -> None:
    from app import main
    from app.core import storage

    monkeypatch.setattr(main.settings, "storage_driver", "local")
    monkeypatch.setattr(storage.settings, "storage_driver", "local")
    monkeypatch.setattr(main.settings, "local_storage_dir", str(tmp_path))
    monkeypatch.setattr(storage.settings, "local_storage_dir", str(tmp_path))
    media = tmp_path / "compose" / "result.mp4"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"local-video")

    response = await client.get("/media/compose/result.mp4")

    assert response.status_code == 200
    assert response.content == b"local-video"


async def test_s3_media_proxy_preserves_range_response(client: AsyncClient, monkeypatch) -> None:
    from app import main
    from app.core import storage

    class FakeBody:
        def iter_chunks(self, chunk_size: int):
            assert chunk_size > 0
            yield b"vide"

        def close(self) -> None:
            return None

    class FakeS3Client:
        def get_object(self, **kwargs):
            assert kwargs == {
                "Bucket": "oral-media",
                "Key": "compose/result.mp4",
                "Range": "bytes=0-3",
            }
            return {
                "Body": FakeBody(),
                "ContentLength": 4,
                "ContentRange": "bytes 0-3/10",
                "ContentType": "video/mp4",
                "ETag": '"media-etag"',
            }

    monkeypatch.setattr(main.settings, "storage_driver", "s3")
    monkeypatch.setattr(storage.settings, "storage_driver", "s3")
    monkeypatch.setattr(storage, "_s3_client", lambda: FakeS3Client(), raising=False)

    response = await client.get(
        "/media/compose/result.mp4",
        headers={"Range": "bytes=0-3"},
    )

    assert response.status_code == 206
    assert response.content == b"vide"
    assert response.headers["content-range"] == "bytes 0-3/10"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["etag"] == '"media-etag"'


async def test_local_media_rejects_path_traversal(client: AsyncClient, tmp_path: Path, monkeypatch) -> None:
    from app import main
    from app.core import storage

    monkeypatch.setattr(main.settings, "storage_driver", "local")
    monkeypatch.setattr(storage.settings, "storage_driver", "local")
    monkeypatch.setattr(main.settings, "local_storage_dir", str(tmp_path))
    monkeypatch.setattr(storage.settings, "local_storage_dir", str(tmp_path))

    response = await client.get("/media/%2E%2E/outside.txt")

    assert response.status_code == 404


async def test_s3_media_maps_missing_object_to_not_found(client: AsyncClient, monkeypatch) -> None:
    from app import main
    from app.core import storage

    class MissingS3Client:
        def get_object(self, **kwargs):
            raise ClientError(
                {
                    "Error": {"Code": "NoSuchKey"},
                    "ResponseMetadata": {"HTTPStatusCode": 404},
                },
                "GetObject",
            )

    monkeypatch.setattr(main.settings, "storage_driver", "s3")
    monkeypatch.setattr(storage.settings, "storage_driver", "s3")
    monkeypatch.setattr(storage, "_s3_client", lambda: MissingS3Client(), raising=False)

    response = await client.get("/media/compose/missing.mp4")

    assert response.status_code == 404
    assert response.json()["detail"] == "媒体文件不存在"
