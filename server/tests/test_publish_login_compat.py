"""Browser launch and QR login compatibility regressions."""

from pathlib import Path
from types import SimpleNamespace

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
