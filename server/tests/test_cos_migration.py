"""Resumable Tencent COS migration and CAM policy tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from scripts.cos_migration import (
    Manifest,
    MigrationOptions,
    S3Location,
    S3Migration,
    should_sample_sha256,
)
from scripts.migrate_storage_to_cos import build_parser


class _Paginator:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    def paginate(self, *, Bucket: str, Prefix: str):  # noqa: N803
        del Bucket
        contents = [
            {"Key": key, "Size": len(value), "ETag": f'"etag-{key}"'}
            for key, value in sorted(self.objects.items())
            if key.startswith(Prefix)
        ]
        yield {"Contents": contents}


class _FakeS3:
    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects = dict(objects or {})
        self.uploaded_keys: list[str] = []
        self.downloaded_keys: list[str] = []

    def get_paginator(self, name: str) -> _Paginator:
        assert name == "list_objects_v2"
        return _Paginator(self.objects)

    def head_object(self, *, Bucket: str, Key: str):  # noqa: N803
        del Bucket
        if Key not in self.objects:
            raise ClientError(
                {
                    "Error": {"Code": "NoSuchKey"},
                    "ResponseMetadata": {"HTTPStatusCode": 404},
                },
                "HeadObject",
            )
        return {
            "ContentLength": len(self.objects[Key]),
            "ETag": f'"etag-{Key}"',
        }

    def download_file(
        self,
        bucket: str,
        key: str,
        filename: str,
        *,
        Config: object,
    ) -> None:
        del bucket, Config
        self.downloaded_keys.append(key)
        Path(filename).write_bytes(self.objects[key])

    def upload_file(
        self,
        filename: str,
        bucket: str,
        key: str,
        *,
        Config: object,
    ) -> None:
        del bucket, Config
        self.uploaded_keys.append(key)
        self.objects[key] = Path(filename).read_bytes()


def _location(name: str) -> S3Location:
    return S3Location(
        endpoint_url=("http://minio.internal:9000" if name == "source" else "https://cos.ap-guangzhou.myqcloud.com"),
        region="us-east-1" if name == "source" else "ap-guangzhou",
        bucket="oral-media" if name == "source" else "oral-media-1250000000",
        access_key=f"{name}-access-secret-value",
        secret_key=f"{name}-secret-key-value-that-must-not-leak",
        addressing_style="path" if name == "source" else "virtual",
    )


def _migration(
    tmp_path: Path,
    *,
    source_client: _FakeS3,
    target_client: _FakeS3,
    options: MigrationOptions,
) -> S3Migration:
    return S3Migration(
        source=_location("source"),
        target=_location("target"),
        options=options,
        manifest_path=tmp_path / "manifest.jsonl",
        checkpoint_path=tmp_path / "checkpoint.json",
        source_client=source_client,
        target_client=target_client,
    )


def test_dry_run_never_writes_target(tmp_path: Path) -> None:
    source = _FakeS3({"videos/a.mp4": b"video"})
    target = _FakeS3()
    migration = _migration(
        tmp_path,
        source_client=source,
        target_client=target,
        options=MigrationOptions(dry_run=True),
    )

    stats = migration.run()

    assert stats.planned == 1
    assert target.uploaded_keys == []
    record = json.loads((tmp_path / "manifest.jsonl").read_text().strip())
    assert record["key"] == "videos/a.mp4"
    assert record["status"] == "planned"


def test_copy_preserves_key_and_writes_secret_free_manifest(tmp_path: Path) -> None:
    source = _FakeS3({"nested/path/video.mp4": b"video-bytes"})
    target = _FakeS3()
    migration = _migration(
        tmp_path,
        source_client=source,
        target_client=target,
        options=MigrationOptions(sample_sha256_rate=1),
    )

    stats = migration.run()

    assert stats.copied == 1
    assert target.uploaded_keys == ["nested/path/video.mp4"]
    assert target.objects["nested/path/video.mp4"] == b"video-bytes"
    combined = (tmp_path / "manifest.jsonl").read_text() + (tmp_path / "checkpoint.json").read_text()
    assert "source-access-secret-value" not in combined
    assert "target-secret-key-value-that-must-not-leak" not in combined
    assert json.loads((tmp_path / "manifest.jsonl").read_text())["sourceSha256"]


def test_resume_skips_completed_manifest_keys(tmp_path: Path) -> None:
    source = _FakeS3({"a.mp4": b"a", "b.mp4": b"b"})
    target = _FakeS3({"a.mp4": b"a"})
    manifest = Manifest(tmp_path / "manifest.jsonl")
    manifest.append({"key": "a.mp4", "status": "copied"})
    migration = _migration(
        tmp_path,
        source_client=source,
        target_client=target,
        options=MigrationOptions(resume=True, sample_sha256_rate=0),
    )

    stats = migration.run()

    assert stats.resumed == 1
    assert target.uploaded_keys == ["b.mp4"]


def test_verify_only_fails_closed_on_size_mismatch(tmp_path: Path) -> None:
    source = _FakeS3({"video.mp4": b"source"})
    target = _FakeS3({"video.mp4": b"different-size"})
    migration = _migration(
        tmp_path,
        source_client=source,
        target_client=target,
        options=MigrationOptions(verify_only=True, sample_sha256_rate=0),
    )

    stats = migration.run()

    assert stats.errors == 1
    assert stats.verified == 0
    assert target.uploaded_keys == []
    record = json.loads((tmp_path / "manifest.jsonl").read_text())
    assert record["status"] == "error"
    assert record["errorType"] == "MigrationVerificationError"


def test_sha256_sampling_is_deterministic() -> None:
    first = [should_sample_sha256(f"key-{index}", 0.2) for index in range(100)]
    second = [should_sample_sha256(f"key-{index}", 0.2) for index in range(100)]

    assert first == second
    assert any(first)
    assert not all(first)


def test_target_requires_official_cos_endpoint_virtual_addressing_and_full_bucket() -> None:
    base = _location("target")

    with pytest.raises(Exception, match="腾讯云 COS Endpoint"):
        S3Location(**{**base.__dict__, "endpoint_url": "https://s3.example.com"}).validate(target=True)
    with pytest.raises(Exception, match="virtual"):
        S3Location(**{**base.__dict__, "addressing_style": "path"}).validate(target=True)
    with pytest.raises(Exception, match="BucketName-APPID"):
        S3Location(**{**base.__dict__, "bucket": "oral-media"}).validate(target=True)


def test_manifest_records_include_schema_version(tmp_path: Path) -> None:
    manifest = Manifest(tmp_path / "manifest.jsonl")
    manifest.append({"key": "a.mp4", "status": "copied"})

    record = json.loads((tmp_path / "manifest.jsonl").read_text())
    assert record["schemaVersion"] == 1


def test_cli_does_not_accept_secret_command_line_arguments() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--source-secret-key", "must-not-be-in-process-list"])


def test_cam_templates_are_scoped_and_have_required_actions() -> None:
    root = Path(__file__).resolve().parents[2]
    runtime = json.loads((root / "deploy/tencent-cos/cam-runtime-policy.template.json").read_text())
    source = json.loads((root / "deploy/tencent-cos/cam-migration-source-policy.template.json").read_text())

    for policy in (runtime, source):
        for statement in policy["statement"]:
            assert statement["effect"] == "allow"
            assert "*" not in statement["action"]
            assert all(resource != "*" for resource in statement["resource"])
            assert all("${BUCKET}-${APPID}" in resource for resource in statement["resource"])

    runtime_actions = {action for statement in runtime["statement"] for action in statement["action"]}
    assert {
        "name/cos:HeadBucket",
        "name/cos:GetObject",
        "name/cos:HeadObject",
        "name/cos:PutObject",
        "name/cos:DeleteObject",
        "name/cos:InitiateMultipartUpload",
        "name/cos:UploadPart",
        "name/cos:CompleteMultipartUpload",
        "name/cos:AbortMultipartUpload",
    } <= runtime_actions
