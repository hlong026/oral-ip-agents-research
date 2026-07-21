"""S3-03 Douyin IM connection contract."""

import asyncio
import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from app.providers.im import douyin_im
from app.providers.im.douyin_im import (
    DouyinIMConfigError,
    DouyinIMConnection,
    DouyinIMProvider,
    DouyinIMSessionError,
    DouyinIMUnsupportedError,
    compute_access_key,
    normalize_douyin_session,
)


def test_normalizes_playwright_storage_state_and_access_key(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = douyin_im.get_settings()
    monkeypatch.setattr(settings, "douyin_im_app_key", "app-key")
    monkeypatch.setattr(settings, "douyin_im_fpid", "9")
    monkeypatch.setattr(settings, "douyin_im_access_key_suffix", "suffix")

    session = normalize_douyin_session(
        {
            "cookies": [
                {"domain": ".douyin.com", "name": "sessionid", "value": "sid-123"},
                {"domain": "www.douyin.com", "name": "ttwid", "value": "ttwid-456"},
                {"domain": "example.com", "name": "ignored", "value": "nope"},
            ],
            "origins": [
                {
                    "origin": "https://www.douyin.com",
                    "localStorage": [{"name": "oral_im_device_id", "value": "9876543210123456789"}],
                }
            ],
        }
    )

    assert session["sessionid"] == "sid-123"
    assert session["device_id"] == "9876543210123456789"
    assert session["cookie_str"] == "sessionid=sid-123; ttwid=ttwid-456"
    assert compute_access_key("9876543210123456789") == hashlib.md5(
        b"9app-key9876543210123456789suffix"
    ).hexdigest()


def test_access_key_rejects_missing_app_key(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = douyin_im.get_settings()
    monkeypatch.setattr(settings, "douyin_im_app_key", "")
    monkeypatch.setattr(settings, "douyin_im_access_key_suffix", "suffix")

    with pytest.raises(DouyinIMConfigError, match="DOUYIN_IM_APP_KEY"):
        compute_access_key("9876543210123456789")


def test_normalization_rejects_missing_session_or_device() -> None:
    with pytest.raises(DouyinIMSessionError, match="sessionid"):
        normalize_douyin_session({"cookies": []})

    with pytest.raises(DouyinIMSessionError, match="device_id"):
        normalize_douyin_session({"cookie_str": "sessionid=sid-123"})


async def test_listen_uses_locked_ws_url_headers_and_subprotocols(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = douyin_im.get_settings()
    monkeypatch.setattr(settings, "douyin_im_app_key", "app-key")
    monkeypatch.setattr(settings, "douyin_im_aid", "6383")
    monkeypatch.setattr(settings, "douyin_im_fpid", "9")
    monkeypatch.setattr(settings, "douyin_im_access_key_suffix", "suffix")

    captured: dict[str, object] = {}

    class OneShotWebSocket:
        async def __aenter__(self) -> "OneShotWebSocket":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        def __aiter__(self) -> "OneShotWebSocket":
            return self

        async def __anext__(self) -> bytes:
            raise StopAsyncIteration

        async def close(self) -> None:
            return None

    def fake_connect(url: str, **kwargs: object) -> OneShotWebSocket:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return OneShotWebSocket()

    monkeypatch.setitem(sys.modules, "websockets", types.SimpleNamespace(connect=fake_connect))

    connection = DouyinIMConnection(
        {
            "sessionid": "sid-123",
            "device_id": "9876543210123456789",
            "cookie_str": "sessionid=sid-123; ttwid=ttwid-456",
        }
    )
    await connection.listen(lambda _message: asyncio.sleep(0))

    parsed = urlparse(str(captured["url"]))
    query = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == douyin_im.IM_WS_URL
    assert query == {
        "aid": ["6383"],
        "device_platform": ["douyin_pc"],
        "fpid": ["9"],
        "device_id": ["9876543210123456789"],
        "token": ["sid-123"],
        "access_key": [hashlib.md5(b"9app-key9876543210123456789suffix").hexdigest()],
    }
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["additional_headers"] == {
        **douyin_im.COMMON_HEADERS,
        "Cookie": "sessionid=sid-123; ttwid=ttwid-456",
    }
    assert kwargs["origin"] == douyin_im.DOUYIN_ORIGIN
    assert kwargs["subprotocols"] == ["binary", "base64", "pbbp2"]


async def test_send_and_create_conversation_fail_closed_without_fixed_request_contract() -> None:
    provider = DouyinIMProvider()
    session = {"sessionid": "sid-123", "device_id": "9876543210123456789", "cookie_str": "sessionid=sid-123"}

    with pytest.raises(DouyinIMUnsupportedError, match="固定 Request protobuf"):
        await provider.send_message(session, "conv", "short", "ticket", "你好")

    with pytest.raises(DouyinIMUnsupportedError, match="固定 Request protobuf"):
        await provider.create_conversation(session, 123)


def test_vendor_stores_device_id_in_valid_storage_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_vendor_douyin_main(monkeypatch)
    state_path = tmp_path / "douyin.json"
    state_path.write_text(
        json.dumps(
            {
                "cookies": [],
                "origins": [
                    {
                        "origin": "https://www.douyin.com",
                        "localStorage": [{"name": "keep", "value": "yes"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    module._store_douyin_device_id(str(state_path), "9876543210123456789")
    module._store_douyin_device_id(str(state_path), "9876543210123456790")

    state = json.loads(state_path.read_text(encoding="utf-8"))
    local_storage = state["origins"][0]["localStorage"]
    assert {"name": "keep", "value": "yes"} in local_storage
    assert [item for item in local_storage if item["name"] == "oral_im_device_id"] == [
        {"name": "oral_im_device_id", "value": "9876543210123456790"}
    ]


def _load_vendor_douyin_main(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    monkeypatch.setitem(sys.modules, "patchright", types.ModuleType("patchright"))
    monkeypatch.setitem(
        sys.modules,
        "patchright.async_api",
        types.SimpleNamespace(Page=object, Playwright=object, async_playwright=lambda: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "conf",
        types.SimpleNamespace(BASE_DIR="", DEBUG_MODE=False, LOCAL_CHROME_HEADLESS=True, LOCAL_CHROME_PATH=""),
    )
    monkeypatch.setitem(sys.modules, "uploader", types.ModuleType("uploader"))
    monkeypatch.setitem(sys.modules, "uploader.base_video", types.SimpleNamespace(BaseVideoUploader=object))
    monkeypatch.setitem(sys.modules, "utils", types.ModuleType("utils"))
    monkeypatch.setitem(
        sys.modules,
        "utils.base_social_media",
        types.SimpleNamespace(set_init_script=lambda context: context),
    )
    monkeypatch.setitem(
        sys.modules,
        "utils.login_qrcode",
        types.SimpleNamespace(
            build_login_qrcode_path=lambda account_file: account_file,
            decode_qrcode_from_path=lambda _path: "",
            print_terminal_qrcode=lambda *_args: None,
            remove_qrcode_file=lambda _path: False,
            save_data_url_image=lambda _src, path: path,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "utils.log",
        types.SimpleNamespace(
            douyin_logger=types.SimpleNamespace(info=lambda *_args: None, warning=lambda *_args: None)
        ),
    )

    module_path = (
        Path(__file__).parents[2] / "vendor" / "social-auto-upload" / "uploader" / "douyin_uploader" / "main.py"
    )
    spec = importlib.util.spec_from_file_location("vendor_douyin_main_s3_03", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
