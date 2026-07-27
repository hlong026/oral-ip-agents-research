"""SAU publish logs must not persist authentication material."""

from pathlib import Path

import pytest

from app.providers.publish.sau_conf import setup_sau

setup_sau()

from uploader.douyin_uploader import main as douyin_module  # noqa: E402


class _CaptureLogger:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, message: str) -> None:
        self.messages.append(message)

    def success(self, message: str) -> None:
        self.messages.append(message)

    def warning(self, message: str) -> None:
        self.messages.append(message)


class _SmsInput:
    def __init__(self) -> None:
        self.filled = ""

    async def click(self) -> None:
        return None

    async def fill(self, value: str) -> None:
        self.filled = value


class _MissingLocator:
    @property
    def first(self) -> "_MissingLocator":
        return self

    async def count(self) -> int:
        return 0

    async def is_visible(self) -> bool:
        return False


class _Keyboard:
    async def press(self, _key: str) -> None:
        return None


class _Page:
    def __init__(self) -> None:
        self.keyboard = _Keyboard()

    def locator(self, _selector: str) -> _MissingLocator:
        return _MissingLocator()

    def get_by_text(self, _text: str, *, exact: bool) -> _MissingLocator:
        assert exact is True
        return _MissingLocator()

    async def wait_for_timeout(self, _milliseconds: int) -> None:
        return None


@pytest.mark.asyncio
async def test_douyin_sms_code_is_used_but_never_logged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _CaptureLogger()
    monkeypatch.setattr(douyin_module, "douyin_logger", capture)
    uploader = object.__new__(douyin_module.DouYinVideo)
    sms_input = _SmsInput()
    code = "482913"

    await uploader._submit_sms_verify_code(
        _Page(),
        sms_input,
        code,
        str(tmp_path / "missing-code.txt"),
    )

    assert sms_input.filled == code
    assert all(code not in message for message in capture.messages)
