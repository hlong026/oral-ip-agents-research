from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"expected block not found in {path}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# 1. Storage: materialize S3 objects as private local files for local-only consumers.
replace_once(
    "server/app/core/storage.py",
    "import os\nimport time\nimport uuid\nfrom collections.abc import AsyncIterator\nfrom pathlib import Path, PurePosixPath\n",
    "import os\nimport tempfile\nimport time\nimport uuid\nfrom collections.abc import AsyncIterator\nfrom contextlib import asynccontextmanager\nfrom pathlib import Path, PurePosixPath\n",
)
replace_once(
    "server/app/core/storage.py",
    "    return boto3.client(\n        \"s3\",\n        endpoint_url=settings.s3_endpoint,\n        aws_access_key_id=settings.s3_access_key,\n        aws_secret_access_key=settings.s3_secret_key,\n        config=Config(connect_timeout=5, read_timeout=30, retries={\"max_attempts\": 2}),\n    )\n\n\nasync def save_bytes",
    "    return boto3.client(\n        \"s3\",\n        endpoint_url=settings.s3_endpoint,\n        aws_access_key_id=settings.s3_access_key,\n        aws_secret_access_key=settings.s3_secret_key,\n        config=Config(connect_timeout=5, read_timeout=30, retries={\"max_attempts\": 2}),\n    )\n\n\ndef _is_missing_object_error(exc: ClientError) -> bool:\n    return exc.response.get(\"Error\", {}).get(\"Code\") in {\"404\", \"NoSuchKey\", \"NotFound\"}\n\n\nasync def save_bytes",
)
replace_once(
    "server/app/core/storage.py",
    "    except ClientError as exc:\n        if exc.response.get(\"Error\", {}).get(\"Code\") in {\"404\", \"NoSuchKey\", \"NotFound\"}:\n            raise FileNotFoundError(key) from exc\n        raise\n\n\nasync def size",
    "    except ClientError as exc:\n        if _is_missing_object_error(exc):\n            raise FileNotFoundError(key) from exc\n        raise\n\n\nasync def download_to_path(key: str, target: Path) -> None:\n    \"\"\"Download an S3 object to disk without buffering the complete object in memory.\"\"\"\n    key = _validated_key(key)\n    if settings.storage_driver == \"local\":\n        raise StorageConfigurationError(\"local storage does not require download_to_path\")\n    target.parent.mkdir(parents=True, exist_ok=True)\n    client = _s3_client()\n    try:\n        await asyncio.to_thread(client.download_file, settings.s3_bucket, key, str(target))\n    except ClientError as exc:\n        if _is_missing_object_error(exc):\n            raise FileNotFoundError(key) from exc\n        raise\n    await asyncio.to_thread(target.chmod, 0o600)\n\n\n@asynccontextmanager\nasync def materialized_path(key: str, *, name: str = \"media\") -> AsyncIterator[Path]:\n    \"\"\"Provide a local path and clean temporary S3 downloads on context exit.\"\"\"\n    key = _validated_key(key)\n    if settings.storage_driver == \"local\":\n        yield local_path(key)\n        return\n\n    with tempfile.TemporaryDirectory(prefix=\"oral-media-\") as directory:\n        temp_dir = Path(directory)\n        await asyncio.to_thread(temp_dir.chmod, 0o700)\n        suffix = Path(key).suffix or \".bin\"\n        target = temp_dir / f\"{name}{suffix}\"\n        await download_to_path(key, target)\n        yield target\n\n\nasync def size",
)
# Normalize the remaining missing-object checks without changing async exists semantics.
storage_path = ROOT / "server/app/core/storage.py"
storage_text = storage_path.read_text(encoding="utf-8")
storage_text = storage_text.replace(
    'if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:',
    "if _is_missing_object_error(exc):",
)
storage_path.write_text(storage_text, encoding="utf-8")

# 2. Common SAU driver: materialize video and cover inside one cleanup scope.
replace_once(
    "server/app/providers/publish/base_driver.py",
    "import asyncio\nimport uuid\nfrom typing import Any\n",
    "import asyncio\nimport uuid\nfrom contextlib import AsyncExitStack\nfrom typing import Any\n",
)
replace_once(
    "server/app/providers/publish/base_driver.py",
    "from app.core.storage import local_path\n",
    "from app.core.storage import materialized_path\n",
)
replace_once(
    "server/app/providers/publish/base_driver.py",
    "        # 1. 视频/封面 → 本地绝对路径\n        import json\n\n        video_path = str(local_path(video_key))\n        cover_path = str(local_path(cover_key)) if cover_key else None\n\n        # 2. 定时发布时间解析\n",
    "        # 1. 视频/封面由对象存储按需物化到 Worker 私有临时目录。\n        import json\n\n        # 2. 定时发布时间解析\n",
)
replace_once(
    "server/app/providers/publish/base_driver.py",
    "        # 4. 在浏览器槽位内执行发布\n        try:\n            async with BrowserSlot():\n                post_id = await self._do_publish(\n                    cookie_file=cookie_file,\n                    video_path=video_path,\n                    title=title,\n                    topics=topics,\n                    cover_path=cover_path,\n                    publish_date=publish_date,\n                )\n",
    "        # 4. 在浏览器槽位内执行发布；退出上下文后清理 S3 临时媒体。\n        try:\n            async with AsyncExitStack() as media_stack:\n                video_path = await media_stack.enter_async_context(\n                    materialized_path(video_key, name=\"video\")\n                )\n                cover_path = (\n                    await media_stack.enter_async_context(\n                        materialized_path(cover_key, name=\"cover\")\n                    )\n                    if cover_key\n                    else None\n                )\n                async with BrowserSlot():\n                    post_id = await self._do_publish(\n                        cookie_file=cookie_file,\n                        video_path=str(video_path),\n                        title=title,\n                        topics=topics,\n                        cover_path=str(cover_path) if cover_path else None,\n                        publish_date=publish_date,\n                    )\n",
)

# 3. Publish export package: build on disk and stream archive into storage.
replace_once(
    "server/app/modules/publish/service.py",
    "import json\nimport zipfile\nfrom datetime import UTC, datetime, timedelta\nfrom io import BytesIO\nfrom pathlib import Path\n\nfrom fastapi import HTTPException, status\n",
    "import asyncio\nimport json\nimport zipfile\nfrom contextlib import AsyncExitStack\nfrom datetime import UTC, datetime, timedelta\nfrom pathlib import Path\nfrom tempfile import TemporaryDirectory\n\nimport aiofiles\nfrom fastapi import HTTPException, status\n",
)
replace_once(
    "server/app/modules/publish/service.py",
    "from app.core.storage import read_bytes, save_bytes, signed_media_path\n",
    "from app.core.storage import materialized_path, save_stream, signed_media_path\n",
)
service_path = ROOT / "server/app/modules/publish/service.py"
service_text = service_path.read_text(encoding="utf-8")
start = service_text.index("async def export_job(")
end = service_text.index("\n\n# ============ 发布执行器", start)
new_export = '''async def export_job(db: AsyncSession, user_id: str, job_id: str) -> ExportOut:
    """生成视频、封面和元数据齐全的人工发布 ZIP 包。"""
    j = await _must_job(db, job_id, user_id)
    if not j.video_key:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "NO_VIDEO", "message": "该任务无成片可导出"}
        )
    video_name = f"video{Path(j.video_key).suffix or '.mp4'}"
    cover_name = f"cover{Path(j.cover_key).suffix or '.jpg'}" if j.cover_key else ""
    metadata: dict[str, object] = {
        "jobId": j.id,
        "taskId": j.task_id,
        "platform": j.platform,
        "platformName": PLATFORM_NAMES.get(j.platform, j.platform),
        "title": j.title,
        "topics": json.loads(j.topics_json or "[]"),
        "scheduledAt": j.scheduled_at or None,
        "videoFilename": video_name,
        "coverFilename": cover_name or None,
        "createdAt": j.created_at.astimezone(UTC).isoformat(),
    }
    try:
        with TemporaryDirectory(prefix="oral-publish-package-") as directory:
            package_path = Path(directory) / f"{j.id}.zip"
            async with AsyncExitStack() as media_stack:
                video_path = await media_stack.enter_async_context(
                    materialized_path(j.video_key, name="video")
                )
                cover_path = (
                    await media_stack.enter_async_context(
                        materialized_path(j.cover_key, name="cover")
                    )
                    if j.cover_key
                    else None
                )

                def build_package() -> None:
                    with zipfile.ZipFile(
                        package_path, "w", compression=zipfile.ZIP_DEFLATED
                    ) as archive:
                        archive.write(video_path, video_name)
                        if cover_path:
                            archive.write(cover_path, cover_name)
                        archive.writestr(
                            "metadata.json",
                            json.dumps(metadata, ensure_ascii=False, indent=2),
                        )

                await asyncio.to_thread(build_package)
            package_size = await asyncio.to_thread(lambda: package_path.stat().st_size)
            async with aiofiles.open(package_path, "rb") as package:
                j.export_key, _ = await save_stream(
                    "publish-packages",
                    f"{j.id}.zip",
                    package,
                    max_bytes=package_size,
                )
    except Exception as exc:  # noqa: BLE001
        logger.exception("publish_package_failed", job_id=j.id, user_id=user_id)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "EXPORT_PACKAGE_FAILED", "message": "发布包生成失败，请稍后重试"},
        ) from exc
    if j.status != "success":
        j.status = "export_ready"
    await repo.save_job(db, j)
    return ExportOut(
        jobId=j.id,
        videoUrl=signed_media_path(j.video_key),
        packageKey=j.export_key,
        packageUrl=signed_media_path(j.export_key),
        metadata=metadata,
    )
'''
service_path.write_text(service_text[:start] + new_export + service_text[end:], encoding="utf-8")

# 4. Tests: S3 materialization, permissions, cleanup, local passthrough and disk-backed ZIP.
security_path = ROOT / "server/tests/test_publish_security.py"
security_text = security_path.read_text(encoding="utf-8")
security_text = security_text.replace(
    "import json\nimport stat\nimport uuid\n\nfrom app.core.db",
    "import asyncio\nimport json\nimport stat\nimport uuid\nfrom pathlib import Path\nfrom typing import Any\n\nimport pytest\nfrom botocore.exceptions import ClientError\n\nfrom app.core.db",
    1,
)
security_tests = r'''

class _DummyBrowserSlot:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: object) -> None:
        return None


class _RecordingPublishDriver:
    def __init__(self, base_cls: type) -> None:
        class Driver(base_cls):
            platform = "douyin"

            def __init__(self) -> None:
                super().__init__()
                self.paths_seen: dict[str, str | None] = {}
                self.parent_modes_seen: dict[str, int | None] = {}

            async def _do_login(self, ticket: str, account_file: str) -> None:
                raise NotImplementedError

            async def _do_publish(
                self,
                cookie_file: str,
                video_path: str,
                title: str,
                topics: list[str],
                cover_path: str | None,
                publish_date: Any,
            ) -> str:
                self.paths_seen = {"video": video_path, "cover": cover_path}
                assert cover_path is not None
                video_stat = await asyncio.to_thread(Path(video_path).parent.stat)
                cover_stat = await asyncio.to_thread(Path(cover_path).parent.stat)
                self.parent_modes_seen = {
                    "video": stat.S_IMODE(video_stat.st_mode),
                    "cover": stat.S_IMODE(cover_stat.st_mode),
                }
                assert await asyncio.to_thread(Path(video_path).read_bytes) == b"video-bytes"
                assert await asyncio.to_thread(Path(cover_path).read_bytes) == b"cover-bytes"
                return "post-1"

            async def _do_check_cookie(self, cookie_file: str) -> bool:
                return True

        self.driver = Driver()


async def test_s3_publish_materializes_media_to_private_temp_files_and_cleans_up(monkeypatch) -> None:
    from app.core import storage
    from app.providers.publish import base_driver

    class FakeS3Client:
        objects = {
            "videos/one.mp4": b"video-bytes",
            "covers/one.jpg": b"cover-bytes",
        }

        def download_file(self, bucket: str, key: str, filename: str) -> None:
            assert bucket == "test-bucket"
            Path(filename).write_bytes(self.objects[key])

    monkeypatch.setattr(storage.settings, "storage_driver", "s3")
    monkeypatch.setattr(storage.settings, "s3_bucket", "test-bucket")
    monkeypatch.setattr(storage, "_s3_client", lambda: FakeS3Client())
    monkeypatch.setattr(base_driver, "BrowserSlot", _DummyBrowserSlot)

    wrapped = _RecordingPublishDriver(base_driver.SAUPublishDriverBase)
    assert (
        await wrapped.driver.publish(
            account_session={"cookies": []},
            video_key="videos/one.mp4",
            title="标题",
            topics=["topic"],
            cover_key="covers/one.jpg",
            account_id="account-1",
        )
        == "post-1"
    )

    video_path = Path(wrapped.driver.paths_seen["video"] or "")
    cover_path = Path(wrapped.driver.paths_seen["cover"] or "")
    assert wrapped.driver.parent_modes_seen == {"video": 0o700, "cover": 0o700}
    assert not await asyncio.to_thread(video_path.exists)
    assert not await asyncio.to_thread(cover_path.exists)


async def test_local_publish_uses_existing_media_paths_without_cleanup(tmp_path, monkeypatch) -> None:
    from app.core import storage
    from app.providers.publish import base_driver

    monkeypatch.setattr(storage.settings, "storage_driver", "local")
    monkeypatch.setattr(storage.settings, "local_storage_dir", str(tmp_path))
    monkeypatch.setattr(base_driver, "BrowserSlot", _DummyBrowserSlot)
    video_path = tmp_path / "videos/one.mp4"
    cover_path = tmp_path / "covers/one.jpg"
    video_path.parent.mkdir(parents=True)
    cover_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"video-bytes")
    cover_path.write_bytes(b"cover-bytes")

    wrapped = _RecordingPublishDriver(base_driver.SAUPublishDriverBase)
    await wrapped.driver.publish(
        account_session={"cookies": []},
        video_key="videos/one.mp4",
        title="标题",
        topics=[],
        cover_key="covers/one.jpg",
    )

    assert Path(wrapped.driver.paths_seen["video"] or "") == video_path
    assert Path(wrapped.driver.paths_seen["cover"] or "") == cover_path
    assert video_path.exists()
    assert cover_path.exists()


async def test_s3_materialize_normalizes_no_such_key(monkeypatch) -> None:
    from app.core import storage

    class MissingS3Client:
        def download_file(self, bucket: str, key: str, filename: str) -> None:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "DownloadFile")

    monkeypatch.setattr(storage.settings, "storage_driver", "s3")
    monkeypatch.setattr(storage.settings, "s3_bucket", "test-bucket")
    monkeypatch.setattr(storage, "_s3_client", lambda: MissingS3Client())

    with pytest.raises(FileNotFoundError):
        async with storage.materialized_path("videos/missing.mp4"):
            pass
'''
if "test_s3_publish_materializes_media_to_private_temp_files_and_cleans_up" in security_text:
    raise RuntimeError("publish security tests already present")
security_path.write_text(security_text.rstrip() + security_tests + "\n", encoding="utf-8")

stage_path = ROOT / "server/tests/test_stage_two_publish.py"
stage_text = stage_path.read_text(encoding="utf-8")
stream_test = r'''

async def test_export_package_streams_media_and_archive_from_disk(monkeypatch) -> None:
    from contextlib import asynccontextmanager

    from app.core.storage import local_path
    from app.modules.publish import repository as publish_repo
    from app.modules.publish import service

    video_key = await save_bytes("publish-test", "large-video.mp4", b"video-bytes")
    cover_key = await save_bytes("publish-test", "large-cover.jpg", b"cover-bytes")

    @asynccontextmanager
    async def fake_materialize(key: str, *, name: str = "media"):
        yield local_path(key)

    async def forbid_full_buffer(*_args, **_kwargs):
        raise AssertionError("发布包不得通过 read_bytes/save_bytes 全量缓冲媒体或 ZIP")

    monkeypatch.setattr(service, "materialized_path", fake_materialize)
    monkeypatch.setattr(service, "read_bytes", forbid_full_buffer, raising=False)
    monkeypatch.setattr(service, "save_bytes", forbid_full_buffer, raising=False)

    async with SessionLocal() as db:
        job = await publish_repo.create_job(
            db,
            user_id="stream-package-user",
            task_id="pipeline-stream",
            platform="douyin",
            title="流式发布包",
            video_key=video_key,
            cover_key=cover_key,
            status="failed",
        )
        result = await service.export_job(db, "stream-package-user", job.id)

    package = await read_bytes(result.packageKey)
    with zipfile.ZipFile(BytesIO(package)) as archive:
        assert archive.read("video.mp4") == b"video-bytes"
        assert archive.read("cover.jpg") == b"cover-bytes"
'''
if "test_export_package_streams_media_and_archive_from_disk" in stage_text:
    raise RuntimeError("streaming export test already present")
stage_path.write_text(stage_text.rstrip() + stream_test + "\n", encoding="utf-8")

# 5. Remove the temporary patch machinery and restore read-only CI permissions.
workflow_path = ROOT / ".github/workflows/ci.yml"
workflow_text = workflow_path.read_text(encoding="utf-8")
permissions_block = "\npermissions:\n  contents: write\n  packages: read\n"
workflow_text = workflow_text.replace(permissions_block, "", 1)
step_start = workflow_text.index("      - name: 临时应用发布存储 P0 补丁\n")
step_end = workflow_text.index("      - name: 2. 数据库迁移链\n", step_start)
workflow_path.write_text(workflow_text[:step_start] + workflow_text[step_end:], encoding="utf-8")
Path(__file__).unlink()
