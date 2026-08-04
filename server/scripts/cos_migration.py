"""Resumable S3/MinIO to Tencent COS migration primitives.

The migration preserves object keys and writes an append-only JSONL manifest plus
an atomic checkpoint. Credentials are never included in either file or in the
safe summary returned to callers.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import ClientError

_SUCCESS_STATES = {"copied", "verified", "skipped_existing"}
_MISSING_CODES = {"404", "NoSuchKey", "NotFound"}


class MigrationConfigurationError(ValueError):
    """Migration configuration is incomplete or unsafe."""


class MigrationVerificationError(RuntimeError):
    """Source and target objects do not match."""


@dataclass(frozen=True)
class S3Location:
    endpoint_url: str
    region: str
    bucket: str
    access_key: str
    secret_key: str
    addressing_style: str = "virtual"
    signature_version: str = "s3"

    def validate(self, *, target: bool = False) -> None:
        parsed = urlparse(self.endpoint_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise MigrationConfigurationError("对象存储 Endpoint 无效")
        if target and parsed.scheme != "https":
            raise MigrationConfigurationError("目标腾讯云 COS Endpoint 必须使用 HTTPS")
        if not self.region.strip() or not self.bucket.strip():
            raise MigrationConfigurationError("对象存储 Region 与 Bucket 不能为空")
        if not self.access_key or not self.secret_key:
            raise MigrationConfigurationError("对象存储密钥只能通过环境变量注入且不能为空")
        if self.addressing_style not in {"virtual", "path", "auto"}:
            raise MigrationConfigurationError("addressing_style 仅支持 virtual/path/auto")
        if self.signature_version not in {"s3", "s3v4"}:
            raise MigrationConfigurationError("signature_version 仅支持 s3/s3v4")
        if target:
            expected = f"cos.{self.region}.myqcloud.com"
            if parsed.hostname != expected:
                raise MigrationConfigurationError("目标必须使用与 Region 一致的腾讯云 COS Endpoint")
            if self.addressing_style != "virtual":
                raise MigrationConfigurationError("目标腾讯云 COS 必须使用 virtual 寻址")
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,49}-\d{5,}", self.bucket):
                raise MigrationConfigurationError("目标 COS Bucket 必须使用 BucketName-APPID 完整名称")

    def safe_identity(self) -> dict[str, str]:
        return {
            "endpointHost": urlparse(self.endpoint_url).hostname or "",
            "region": self.region,
            "bucket": self.bucket,
            "addressingStyle": self.addressing_style,
            "signatureVersion": self.signature_version,
        }


@dataclass(frozen=True)
class ObjectMeta:
    key: str
    size: int
    etag: str


@dataclass
class MigrationStats:
    discovered: int = 0
    copied: int = 0
    verified: int = 0
    skipped_existing: int = 0
    resumed: int = 0
    planned: int = 0
    errors: int = 0
    bytes_copied: int = 0


@dataclass(frozen=True)
class MigrationOptions:
    prefix: str = ""
    dry_run: bool = False
    resume: bool = False
    verify_only: bool = False
    sample_sha256_rate: float = 0.05
    max_errors: int = 1
    multipart_threshold_mb: int = 64
    multipart_chunksize_mb: int = 16
    max_concurrency: int = 4

    def validate(self) -> None:
        if self.dry_run and self.verify_only:
            raise MigrationConfigurationError("dry-run 与 verify-only 不能同时使用")
        if not 0 <= self.sample_sha256_rate <= 1:
            raise MigrationConfigurationError("sample_sha256_rate 必须位于 0 到 1")
        if self.max_errors < 1:
            raise MigrationConfigurationError("max_errors 必须大于 0")
        if self.multipart_threshold_mb < 5 or self.multipart_chunksize_mb < 5:
            raise MigrationConfigurationError("Multipart 阈值和分片大小不得小于 5MB")
        if self.max_concurrency < 1:
            raise MigrationConfigurationError("max_concurrency 必须大于 0")


def build_client(location: S3Location) -> Any:
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=location.endpoint_url.rstrip("/"),
        region_name=location.region,
        aws_access_key_id=location.access_key,
        aws_secret_access_key=location.secret_key,
        config=Config(
            signature_version=location.signature_version,
            s3={"addressing_style": location.addressing_style},
            connect_timeout=5,
            read_timeout=120,
            max_pool_connections=16,
            retries={"max_attempts": 4, "mode": "standard"},
        ),
    )


def build_transfer_config(options: MigrationOptions) -> TransferConfig:
    mebibyte = 1024 * 1024
    return TransferConfig(
        multipart_threshold=options.multipart_threshold_mb * mebibyte,
        multipart_chunksize=options.multipart_chunksize_mb * mebibyte,
        max_concurrency=options.max_concurrency,
        use_threads=True,
    )


def normalized_etag(value: str | None) -> str:
    return (value or "").strip().strip('"')


def etags_are_comparable(source: str, target: str) -> bool:
    return bool(source and target and "-" not in source and "-" not in target)


def should_sample_sha256(key: str, rate: float) -> bool:
    if rate <= 0:
        return False
    if rate >= 1:
        return True
    bucket = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big")
    return bucket / (2**64 - 1) < rate


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_objects(client: Any, bucket: str, prefix: str = "") -> Iterator[ObjectMeta]:
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            yield ObjectMeta(
                key=str(item["Key"]),
                size=int(item["Size"]),
                etag=normalized_etag(item.get("ETag")),
            )


class Manifest:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def completed_keys(self) -> set[str]:
        if not self.path.exists():
            return set()
        completed: set[str] = set()
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("status") in _SUCCESS_STATES:
                completed.add(str(record["key"]))
        return completed

    def append(self, record: dict[str, object]) -> None:
        safe = {"schemaVersion": 1, **record}
        for forbidden in ("accessKey", "secretKey", "access_key", "secret_key"):
            safe.pop(forbidden, None)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(safe, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


class Checkpoint:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        *,
        last_key: str,
        stats: MigrationStats,
        source: S3Location,
        target: S3Location,
    ) -> None:
        payload = {
            "schemaVersion": 1,
            "lastKey": last_key,
            "stats": asdict(stats),
            "source": source.safe_identity(),
            "target": target.safe_identity(),
        }
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)


class S3Migration:
    def __init__(
        self,
        *,
        source: S3Location,
        target: S3Location,
        options: MigrationOptions,
        manifest_path: Path,
        checkpoint_path: Path,
        source_client: Any | None = None,
        target_client: Any | None = None,
    ) -> None:
        source.validate()
        target.validate(target=True)
        options.validate()
        self.source = source
        self.target = target
        self.options = options
        self.source_client = source_client or build_client(source)
        self.target_client = target_client or build_client(target)
        self.transfer = build_transfer_config(options)
        self.manifest = Manifest(manifest_path)
        self.checkpoint = Checkpoint(checkpoint_path)
        self.stats = MigrationStats()

    def safe_summary(self) -> dict[str, object]:
        return {
            "source": self.source.safe_identity(),
            "target": self.target.safe_identity(),
            "options": {
                "prefix": self.options.prefix,
                "dryRun": self.options.dry_run,
                "resume": self.options.resume,
                "verifyOnly": self.options.verify_only,
                "sampleSha256Rate": self.options.sample_sha256_rate,
            },
            "stats": asdict(self.stats),
        }

    def _head_target(self, key: str) -> ObjectMeta | None:
        try:
            response = self.target_client.head_object(Bucket=self.target.bucket, Key=key)
        except ClientError as exc:
            if str(exc.response.get("Error", {}).get("Code")) in _MISSING_CODES:
                return None
            raise
        return ObjectMeta(
            key=key,
            size=int(response["ContentLength"]),
            etag=normalized_etag(response.get("ETag")),
        )

    def _download(self, client: Any, bucket: str, key: str, path: Path) -> None:
        client.download_file(bucket, key, str(path), Config=self.transfer)

    def _upload(self, path: Path, key: str) -> None:
        self.target_client.upload_file(
            str(path),
            self.target.bucket,
            key,
            Config=self.transfer,
        )

    def _target_sha256(self, key: str, directory: Path) -> str:
        target_path = directory / "target-object"
        self._download(self.target_client, self.target.bucket, key, target_path)
        return sha256_file(target_path)

    def _verify_metadata(self, source: ObjectMeta, target: ObjectMeta) -> None:
        if source.size != target.size:
            raise MigrationVerificationError(f"size mismatch for {source.key}: {source.size} != {target.size}")
        if etags_are_comparable(source.etag, target.etag) and source.etag != target.etag:
            raise MigrationVerificationError(f"etag mismatch for {source.key}")

    def _verify_existing(self, source: ObjectMeta, sampled: bool) -> dict[str, object]:
        target = self._head_target(source.key)
        if target is None:
            raise MigrationVerificationError(f"target object missing: {source.key}")
        self._verify_metadata(source, target)
        source_sha = ""
        target_sha = ""
        if sampled:
            with tempfile.TemporaryDirectory(prefix="oral-cos-verify-") as directory:
                temp_dir = Path(directory)
                source_path = temp_dir / "source-object"
                self._download(self.source_client, self.source.bucket, source.key, source_path)
                source_sha = sha256_file(source_path)
                target_sha = self._target_sha256(source.key, temp_dir)
            if source_sha != target_sha:
                raise MigrationVerificationError(f"sha256 mismatch for {source.key}")
        return {
            "targetSize": target.size,
            "targetEtag": target.etag,
            "sha256Sampled": sampled,
            "sourceSha256": source_sha,
            "targetSha256": target_sha,
        }

    def run(self) -> MigrationStats:
        completed = self.manifest.completed_keys() if self.options.resume else set()
        for source_meta in iter_objects(
            self.source_client,
            self.source.bucket,
            self.options.prefix,
        ):
            self.stats.discovered += 1
            if source_meta.key in completed:
                self.stats.resumed += 1
                continue
            sampled = should_sample_sha256(
                source_meta.key,
                self.options.sample_sha256_rate,
            )
            try:
                if self.options.dry_run:
                    self.stats.planned += 1
                    self.manifest.append(
                        {
                            "key": source_meta.key,
                            "status": "planned",
                            "sourceSize": source_meta.size,
                            "sourceEtag": source_meta.etag,
                            "sha256Sampled": sampled,
                        }
                    )
                elif self.options.verify_only:
                    details = self._verify_existing(source_meta, sampled)
                    self.stats.verified += 1
                    self.manifest.append(
                        {
                            "key": source_meta.key,
                            "status": "verified",
                            "sourceSize": source_meta.size,
                            "sourceEtag": source_meta.etag,
                            **details,
                        }
                    )
                else:
                    existing = self._head_target(source_meta.key)
                    if existing is not None and existing.size == source_meta.size:
                        details = self._verify_existing(source_meta, sampled)
                        self.stats.skipped_existing += 1
                        self.manifest.append(
                            {
                                "key": source_meta.key,
                                "status": "skipped_existing",
                                "sourceSize": source_meta.size,
                                "sourceEtag": source_meta.etag,
                                **details,
                            }
                        )
                    else:
                        with tempfile.TemporaryDirectory(prefix="oral-cos-copy-") as directory:
                            temp_dir = Path(directory)
                            source_path = temp_dir / "source-object"
                            self._download(
                                self.source_client,
                                self.source.bucket,
                                source_meta.key,
                                source_path,
                            )
                            if source_path.stat().st_size != source_meta.size:
                                raise MigrationVerificationError(f"source download size mismatch for {source_meta.key}")
                            source_sha = sha256_file(source_path) if sampled else ""
                            self._upload(source_path, source_meta.key)
                            target_meta = self._head_target(source_meta.key)
                            if target_meta is None:
                                raise MigrationVerificationError(
                                    f"target object missing after upload: {source_meta.key}"
                                )
                            self._verify_metadata(source_meta, target_meta)
                            target_sha = self._target_sha256(source_meta.key, temp_dir) if sampled else ""
                            if sampled and source_sha != target_sha:
                                raise MigrationVerificationError(f"sha256 mismatch for {source_meta.key}")
                        self.stats.copied += 1
                        self.stats.bytes_copied += source_meta.size
                        self.manifest.append(
                            {
                                "key": source_meta.key,
                                "status": "copied",
                                "sourceSize": source_meta.size,
                                "sourceEtag": source_meta.etag,
                                "targetSize": target_meta.size,
                                "targetEtag": target_meta.etag,
                                "sha256Sampled": sampled,
                                "sourceSha256": source_sha,
                                "targetSha256": target_sha,
                            }
                        )
            except Exception as exc:  # noqa: BLE001
                self.stats.errors += 1
                self.manifest.append(
                    {
                        "key": source_meta.key,
                        "status": "error",
                        "sourceSize": source_meta.size,
                        "sourceEtag": source_meta.etag,
                        "errorType": type(exc).__name__,
                        "error": str(exc)[:300],
                    }
                )
                self.checkpoint.write(
                    last_key=source_meta.key,
                    stats=self.stats,
                    source=self.source,
                    target=self.target,
                )
                if self.stats.errors >= self.options.max_errors:
                    break
                continue
            self.checkpoint.write(
                last_key=source_meta.key,
                stats=self.stats,
                source=self.source,
                target=self.target,
            )
        return self.stats
