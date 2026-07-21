"""
动态 Provider 配置（DB 持久化，内存缓存）
- 前端设置页写入 → provider_config 表
- Provider 运行时通过 get_config(key) 读取凭据
- 缓存 60s 自动失效 / 设置保存时主动失效
"""

import asyncio
import base64
import hashlib
import logging
import time

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("oral.core.dynamic_config")

_cache: dict[str, str] = {}
_cache_ts: float = 0.0
_cache_loaded: bool = False  # 标记是否已成功加载过（解决空表时 not {} 绕过 TTL）
_cache_generation: int = 0  # invalidate 时递增，防止并发加载覆盖新值
_load_lock = asyncio.Lock()
_CACHE_TTL = 60.0  # 秒
_ENC_PREFIX = "enc:v1:"


def _fernet() -> Fernet:
    from app.core.config import get_settings

    settings = get_settings()
    encryption_secret = settings.config_encryption_key
    if not encryption_secret and settings.app_env != "dev":
        raise RuntimeError("生产环境必须配置 CONFIG_ENCRYPTION_KEY")
    secret = (encryption_secret or settings.app_secret).encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def encrypt_config_value(value: str) -> str:
    if not value or value.startswith(_ENC_PREFIX):
        return value
    return _ENC_PREFIX + _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_config_value(value: str) -> str:
    if not value or not value.startswith(_ENC_PREFIX):
        return value
    try:
        return _fernet().decrypt(value.removeprefix(_ENC_PREFIX).encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.warning("provider_config_decrypt_failed")
        return ""


def invalidate_cache() -> None:
    """设置保存后主动清缓存"""
    global _cache, _cache_ts, _cache_loaded, _cache_generation
    _cache = {}
    _cache_ts = 0.0
    _cache_loaded = False
    _cache_generation += 1


async def _load_from_db() -> dict[str, str]:
    """从 DB 加载全部 provider_config"""
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.modules.settings.models import ProviderConfig

    async with SessionLocal() as db:
        result = await db.execute(select(ProviderConfig))
        rows = result.scalars().all()
        return {row.key: decrypt_config_value(row.value) for row in rows}


async def get_config(key: str, default: str = "") -> str:
    """
    获取 Provider 配置值。
    优先读 DB 缓存 → 过期后重新加载 → 无值时回退到 .env 静态配置（兼容迁移期）
    """
    global _cache, _cache_ts, _cache_loaded

    now = time.time()
    if not _cache_loaded or now - _cache_ts > _CACHE_TTL:
        gen = _cache_generation
        async with _load_lock:
            # 双重检查：锁内再判断是否仍需加载（防止并发重复加载）
            if not _cache_loaded or time.time() - _cache_ts > _CACHE_TTL:
                try:
                    loaded = await _load_from_db()
                    # 加载期间若被 invalidate，丢弃旧数据
                    if _cache_generation == gen:
                        _cache = loaded
                        _cache_ts = time.time()
                        _cache_loaded = True
                except Exception as e:
                    logger.debug(f"动态配置加载失败，回退到 .env: {e}")

    val = _cache.get(key, "")
    if val:
        return val

    # 回退：从 .env 静态配置读取（兼容未迁移场景）
    from app.core.config import get_settings

    settings = get_settings()
    return str(getattr(settings, key, default) or default)


async def get_config_int(key: str, default: int = 0) -> int:
    """获取整型配置"""
    val = await get_config(key, str(default))
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


async def get_config_float(key: str, default: float = 0.0) -> float:
    """获取浮点配置。"""
    val = await get_config(key, str(default))
    try:
        return float(val)
    except (ValueError, TypeError):
        return default
