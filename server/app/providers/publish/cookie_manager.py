"""
Cookie 管理器
- DB session_json ↔ 临时文件双向转换
- SAU 的 Playwright storage_state 需要文件路径，我们的 PublishAccount 存 DB
- 发布时：DB → 临时文件 → SAU 使用 → 发布后回写 DB（Cookie 可能刷新）
"""

import json
import os
import tempfile
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger("oral.publish.cookie")

# 临时 Cookie 文件目录（进程生命周期内复用）
_COOKIE_DIR = Path(tempfile.gettempdir()) / "oral_publish_cookies"


def _ensure_cookie_dir() -> None:
    _COOKIE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    _COOKIE_DIR.chmod(0o700)


def _write_private(filepath: Path, content: str) -> None:
    _ensure_cookie_dir()
    descriptor = os.open(filepath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
    filepath.chmod(0o600)


def session_to_file(session_json: str, account_id: str, platform: str) -> str:
    """将 DB 中的 session_json 写入临时文件，返回文件路径供 SAU 使用"""
    filename = f"{platform}_{account_id}.json"
    filepath = _COOKIE_DIR / filename
    try:
        data = json.loads(session_json) if session_json else {}
        _write_private(filepath, json.dumps(data, ensure_ascii=False))
    except (json.JSONDecodeError, TypeError):
        _write_private(filepath, "{}")
    return str(filepath)


def file_to_session(account_id: str, platform: str) -> str:
    """发布完成后，从临时文件回读 Cookie（SAU 发布过程中可能刷新 Cookie）"""
    filename = f"{platform}_{account_id}.json"
    filepath = _COOKIE_DIR / filename
    if not filepath.exists():
        return "{}"
    try:
        return filepath.read_text(encoding="utf-8")
    except OSError:
        return "{}"


def cleanup_cookie_file(account_id: str, platform: str) -> None:
    """清理临时 Cookie 文件"""
    filename = f"{platform}_{account_id}.json"
    filepath = _COOKIE_DIR / filename
    try:
        if filepath.exists():
            filepath.unlink()
    except OSError:
        logger.warning("cookie_temp_cleanup_failed", platform=platform, account_id=account_id)


def create_private_cookie_path(filename: str) -> str:
    filepath = _COOKIE_DIR / filename
    _write_private(filepath, "{}")
    return str(filepath)


def cleanup_cookie_path(filepath: str) -> None:
    try:
        Path(filepath).unlink(missing_ok=True)
    except OSError:
        logger.warning("cookie_temp_cleanup_failed", path=Path(filepath).name)


def get_cookie_dir() -> Path:
    """获取 Cookie 临时目录（供登录流程使用）"""
    _ensure_cookie_dir()
    return _COOKIE_DIR
