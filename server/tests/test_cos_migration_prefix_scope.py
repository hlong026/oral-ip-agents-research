"""COS migration prefix scoping must not rewrite or overreach object keys."""

from pathlib import Path

from scripts.cos_migration import MigrationOptions, S3Location, S3Migration


class _Paginator:
    def paginate(self, *, Bucket: str, Prefix: str):  # noqa: N803
        assert Bucket == "oral-media"
        objects = {
            "compose/2026/a.mp4": b"a",
            "compose/2026/nested/b.mp4": b"bb",
            "voice/2026/c.wav": b"ccc",
        }
        yield {
            "Contents": [
                {"Key": key, "Size": len(value), "ETag": '"etag"'}
                for key, value in objects.items()
                if key.startswith(Prefix)
            ]
        }


class _Source:
    def get_paginator(self, name: str) -> _Paginator:
        assert name == "list_objects_v2"
        return _Paginator()


class _Target:
    pass


def _location(target: bool) -> S3Location:
    return S3Location(
        endpoint_url=(
            "https://cos.ap-guangzhou.myqcloud.com"
            if target
            else "http://minio.internal:9000"
        ),
        region="ap-guangzhou" if target else "us-east-1",
        bucket="oral-media-1250000000" if target else "oral-media",
        access_key="non-placeholder-access-id",
        secret_key="non-placeholder-secret-key-value",
        addressing_style="virtual" if target else "path",
    )


def test_dry_run_prefix_scope_preserves_complete_keys(tmp_path: Path) -> None:
    migration = S3Migration(
        source=_location(False),
        target=_location(True),
        options=MigrationOptions(prefix="compose/2026/", dry_run=True),
        manifest_path=tmp_path / "manifest.jsonl",
        checkpoint_path=tmp_path / "checkpoint.json",
        source_client=_Source(),
        target_client=_Target(),
    )

    stats = migration.run()

    assert stats.discovered == 2
    assert stats.planned == 2
    manifest = (tmp_path / "manifest.jsonl").read_text(encoding="utf-8")
    assert '"key": "compose/2026/a.mp4"' in manifest
    assert '"key": "compose/2026/nested/b.mp4"' in manifest
    assert "voice/2026/c.wav" not in manifest
