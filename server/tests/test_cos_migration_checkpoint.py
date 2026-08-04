"""Atomic and secret-free COS migration checkpoint contract."""

import json

from scripts.cos_migration import Checkpoint, MigrationStats, S3Location


def _location(name: str) -> S3Location:
    return S3Location(
        endpoint_url=(
            "http://minio.internal:9000"
            if name == "source"
            else "https://cos.ap-guangzhou.myqcloud.com"
        ),
        region="us-east-1" if name == "source" else "ap-guangzhou",
        bucket="oral-media" if name == "source" else "oral-media-1250000000",
        access_key=f"{name}-secret-id",
        secret_key=f"{name}-secret-key-that-must-never-be-written",
        addressing_style="path" if name == "source" else "virtual",
    )


def test_checkpoint_is_atomic_and_never_persists_credentials(tmp_path) -> None:
    path = tmp_path / "checkpoint.json"
    checkpoint = Checkpoint(path)

    checkpoint.write(
        last_key="videos/final.mp4",
        stats=MigrationStats(discovered=2, copied=2, bytes_copied=1024),
        source=_location("source"),
        target=_location("target"),
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    combined = path.read_text(encoding="utf-8")
    assert payload["schemaVersion"] == 1
    assert payload["lastKey"] == "videos/final.mp4"
    assert payload["stats"]["copied"] == 2
    assert payload["source"]["bucket"] == "oral-media"
    assert payload["target"]["bucket"] == "oral-media-1250000000"
    assert "secret-id" not in combined
    assert "secret-key" not in combined
    assert not path.with_suffix(".json.tmp").exists()
