"""Publish credential storage and temporary-file security."""

import asyncio
import json
import stat
import uuid
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError

from app.core.db import SessionLocal
from app.modules.publish.models import PublishAccount


async def test_plaintext_publish_sessions_are_migrated_to_encrypted_storage(client) -> None:
    from app.modules.publish.repository import migrate_plaintext_sessions
    from app.modules.publish.session_crypto import decrypt_session_value, is_encrypted_session

    raw_session = json.dumps({"cookies": [{"name": "sessionid", "value": "secret-cookie"}]})
    account_id = uuid.uuid4().hex
    async with SessionLocal() as db:
        db.add(
            PublishAccount(
                id=account_id,
                user_id=uuid.uuid4().hex,
                platform="douyin",
                nickname="旧账号",
                session_json=raw_session,
            )
        )
        await db.commit()

        migrated = await migrate_plaintext_sessions(db)
        account = await db.get(PublishAccount, account_id)

    assert migrated >= 1
    assert account is not None
    assert is_encrypted_session(account.session_json)
    assert decrypt_session_value(account.session_json) == raw_session
    assert "secret-cookie" not in account.session_json


def test_cookie_temp_file_is_private_and_removed(tmp_path, monkeypatch) -> None:
    from app.providers.publish import cookie_manager

    monkeypatch.setattr(cookie_manager, "_COOKIE_DIR", tmp_path)
    cookie_path = cookie_manager.session_to_file(
        json.dumps({"cookies": [{"name": "sessionid", "value": "secret-cookie"}]}),
        "account-test",
        "douyin",
    )

    assert stat.S_IMODE(cookie_manager.Path(cookie_path).stat().st_mode) == 0o600
    assert "secret-cookie" in cookie_manager.Path(cookie_path).read_text(encoding="utf-8")

    cookie_manager.cleanup_cookie_path(cookie_path)
    assert not cookie_manager.Path(cookie_path).exists()


def test_cookie_temp_files_are_unique_per_invocation(tmp_path, monkeypatch) -> None:
    """同账号并发发布/心跳各用独立临时文件，互不覆盖互不误删"""
    from app.providers.publish import cookie_manager

    monkeypatch.setattr(cookie_manager, "_COOKIE_DIR", tmp_path)
    session = json.dumps({"cookies": [{"name": "sessionid", "value": "v1"}]})
    path_a = cookie_manager.session_to_file(session, "account-test", "douyin")
    path_b = cookie_manager.session_to_file(session, "account-test", "douyin")

    assert path_a != path_b
    cookie_manager.cleanup_cookie_path(path_a)
    # 清理 A 不影响 B，B 仍可回读
    assert json.loads(cookie_manager.read_session_file(path_b))["cookies"][0]["value"] == "v1"
    cookie_manager.cleanup_cookie_path(path_b)
    # 文件已删时回读降级为空对象
    assert cookie_manager.read_session_file(path_b) == "{}"


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

        def download_file(self, bucket: str, key: str, filename: str, **_kwargs: object) -> None:
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
        def download_file(self, bucket: str, key: str, filename: str, **_kwargs: object) -> None:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "DownloadFile")

    monkeypatch.setattr(storage.settings, "storage_driver", "s3")
    monkeypatch.setattr(storage.settings, "s3_bucket", "test-bucket")
    monkeypatch.setattr(storage, "_s3_client", lambda: MissingS3Client())

    with pytest.raises(FileNotFoundError):
        async with storage.materialized_path("videos/missing.mp4"):
            pass
