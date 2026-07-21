"""三平台扫码登录公共能力回归测试。"""

import json
from pathlib import Path

import pytest

from app.core.db import SessionLocal
from app.modules.publish import repository as publish_repository
from app.modules.publish import service as publish_service
from app.providers.publish.sau_conf import resolve_browser_executable, setup_sau
from app.providers.registry import registry

setup_sau()

from uploader.douyin_uploader.main import _extract_douyin_device_id  # noqa: E402


def test_explicit_browser_path_wins(tmp_path: Path) -> None:
    browser = tmp_path / "chrome"
    browser.touch()

    assert resolve_browser_executable(str(browser), candidates=[]) == str(browser)


def test_browser_falls_back_to_installed_candidate(tmp_path: Path) -> None:
    browser = tmp_path / "Google Chrome"
    browser.touch()

    assert resolve_browser_executable("", candidates=[browser]) == str(browser)


def test_missing_browser_returns_empty_path(tmp_path: Path) -> None:
    missing = tmp_path / "missing-browser"

    assert resolve_browser_executable("", candidates=[missing]) == ""


def test_extract_douyin_device_id_from_query_user_response() -> None:
    assert _extract_douyin_device_id({"id": 1234567890123456789, "status_code": 0}) == "1234567890123456789"
    assert _extract_douyin_device_id({"status_code": 12}) == ""


@pytest.mark.asyncio
async def test_qrcode_poll_returns_platform_login_error(client, monkeypatch: pytest.MonkeyPatch) -> None:
    class FailedDriver:
        async def check_login(self, ticket: str) -> dict:
            return {"_failed": True, "message": "未获取到视频号登录二维码"}

    monkeypatch.setattr(registry, "publish_driver", lambda platform: FailedDriver())
    async with SessionLocal() as db:
        result = await publish_service.qrcode_poll(db, "user-1", "shipinhao", "ticket-1")

    assert result.status == "expired"
    assert result.message == "未获取到视频号登录二维码"


@pytest.mark.asyncio
async def test_qrcode_poll_success_persists_account_automatically(client, monkeypatch: pytest.MonkeyPatch) -> None:
    class SuccessfulDriver:
        async def check_login(self, ticket: str) -> dict:
            assert ticket == "ticket-xhs-success"
            return {
                "nickname": "测试小红书账号",
                "cookies": [{"name": "web_session", "value": "session-value"}],
            }

    monkeypatch.setattr(registry, "publish_driver", lambda platform: SuccessfulDriver())
    async with SessionLocal() as db:
        result = await publish_service.qrcode_poll(
            db,
            "user-auto-save",
            "xiaohongshu",
            "ticket-xhs-success",
        )
        accounts = await publish_repository.list_accounts(db, "user-auto-save")

    assert result.status == "success"
    assert result.account is not None
    assert result.account.nickname == "测试小红书账号"
    assert len(accounts) == 1
    assert accounts[0].status == "active"
    assert json.loads(accounts[0].session_json)["cookies"][0]["name"] == "web_session"
