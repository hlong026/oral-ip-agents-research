"""Browser launch and QR login compatibility regressions."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.db import SessionLocal
from app.modules.publish import service as publish_service
from app.providers.publish.sau_conf import resolve_browser_executable, setup_sau
from app.providers.registry import registry

setup_sau()


def test_explicit_browser_path_wins(tmp_path: Path) -> None:
    browser = tmp_path / "Google Chrome"
    browser.touch()

    assert resolve_browser_executable(str(browser), candidates=[]) == str(browser)


def test_browser_falls_back_to_installed_candidate(tmp_path: Path) -> None:
    browser = tmp_path / "Google Chrome"
    browser.touch()

    assert resolve_browser_executable("", candidates=[browser]) == str(browser)


def test_missing_browser_keeps_edge_channel_fallback(tmp_path: Path) -> None:
    missing = tmp_path / "missing-browser"

    assert resolve_browser_executable("", candidates=[missing]) == ""


@pytest.mark.asyncio
async def test_publish_materializes_s3_media_for_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.publish import base_driver

    captured: dict[str, bytes | None] = {}

    class FakeDriver(base_driver.SAUPublishDriverBase):
        platform = "douyin"

        async def _do_login(self, ticket: str, account_file: str) -> None:
            raise AssertionError("login is not part of this test")

        async def _do_publish(
            self,
            cookie_file: str,
            video_path: str,
            title: str,
            topics: list[str],
            cover_path: str | None,
            publish_date: Any,
        ) -> str:
            captured["video"] = await asyncio.to_thread(Path(video_path).read_bytes)
            captured["cover"] = await asyncio.to_thread(Path(cover_path).read_bytes) if cover_path else None
            return "post-1"

        async def _do_check_cookie(self, cookie_file: str) -> bool:
            return True

    async def download_remote(key: str, path: Path) -> None:
        await asyncio.to_thread(
            path.write_bytes,
            {"compose/video.mp4": b"video", "compose/cover.jpg": b"cover"}[key],
        )

    monkeypatch.setattr(base_driver, "storage_settings", SimpleNamespace(storage_driver="s3"), raising=False)
    monkeypatch.setattr(base_driver, "download_to_path", download_remote, raising=False)

    post_id = await FakeDriver().publish(
        {},
        "compose/video.mp4",
        "测试发布",
        [],
        "compose/cover.jpg",
        account_id="account-1",
    )

    assert post_id == "post-1"
    assert captured == {"video": b"video", "cover": b"cover"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("driver_message", "expected_message"),
    [("未获取到视频号登录二维码", "未获取到视频号登录二维码"), ("", "登录失败，请重新发起")],
)
async def test_qrcode_poll_returns_platform_login_error(
    client,
    monkeypatch: pytest.MonkeyPatch,
    driver_message: str,
    expected_message: str,
) -> None:
    class FailedDriver:
        async def check_login(self, ticket: str) -> dict:
            assert ticket == "ticket-1"
            return {"_failed": True, "message": driver_message}

    monkeypatch.setattr(publish_service, "_capability", lambda platform: SimpleNamespace(automaticEnabled=True))
    monkeypatch.setattr(registry, "publish_driver", lambda platform: FailedDriver())

    async with SessionLocal() as db:
        result = await publish_service.qrcode_poll(db, "user-1", "shipinhao", "ticket-1")

    assert result.status == "expired"
    assert result.message == expected_message


@pytest.mark.asyncio
async def test_qrcode_poll_keeps_refreshed_qrcode(client, monkeypatch: pytest.MonkeyPatch) -> None:
    class WaitingDriver:
        async def check_login(self, ticket: str) -> dict:
            return {"_waiting": True, "qrcode_url": "data:image/png;base64,refreshed"}

    monkeypatch.setattr(publish_service, "_capability", lambda platform: SimpleNamespace(automaticEnabled=True))
    monkeypatch.setattr(registry, "publish_driver", lambda platform: WaitingDriver())

    async with SessionLocal() as db:
        result = await publish_service.qrcode_poll(db, "user-1", "xiaohongshu", "ticket-2")

    assert result.status == "waiting"
    assert result.qrcodeUrl == "data:image/png;base64,refreshed"
