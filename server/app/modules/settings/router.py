"""Provider 配置控制面。"""

from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.db import get_db
from app.core.deps import require_permission

from .models import ProviderConfig

router = APIRouter(prefix="/settings", tags=["settings"])
provider_router = APIRouter(prefix="/providers", tags=["admin-providers"])

# Provider 密钥/接入点管理为最高敏感操作，仅超管（admin "*" 通配）可执行
_REQUIRE_PROVIDERS_MANAGE = require_permission("providers.manage")

# 前端可配置的 key 白名单
ALLOWED_KEYS = {
    "douyidou_app_id",
    "douyidou_app_secret",
    "douyidou_base_url",
    "dashscope_api_key",
    "dashscope_workspace_id",
    "dashscope_region",
    "asr_model",
    "asr_flash_model",
    "asr_flash_threshold_sec",
    "deepseek_api_key",
    "deepseek_base_url",
    "deepseek_model",
    "deepseek_enabled",
    "deepseek_priority",
    "feiying_api_key",
    "feiying_base_url",
    "feiying_enabled",
    "feiying_priority",
    "dashscope_enabled",
    "dashscope_priority",
    "douyidou_enabled",
    "douyidou_priority",
}

# 敏感 key（GET 时脱敏返回）
SENSITIVE_KEYS = {
    "douyidou_app_secret",
    "dashscope_api_key",
    "deepseek_api_key",
    "feiying_api_key",
}

ALLOWED_BASE_URL_HOSTS = {
    "gateway.diadi.cn",
    "api.deepseek.com",
    "hfw-api.hifly.cc",
}


class SettingsOut(BaseModel):
    settings: dict[str, str]


class SettingsIn(BaseModel):
    settings: dict[str, str]


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    return "configured"


def _validate_provider_setting(key: str, value: str) -> None:
    if not key.endswith("_base_url") or not value:
        return
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_BASE_URL_HOSTS:
        from fastapi import HTTPException, status

        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "PROVIDER_URL_NOT_ALLOWED", "message": "Provider 地址不在服务端白名单中"},
        )


async def _read_settings(db: AsyncSession) -> dict[str, str]:
    from sqlalchemy import select

    from app.core.config import get_settings as get_static_settings
    from app.core.dynamic_config import decrypt_config_value

    result = await db.execute(select(ProviderConfig))
    rows = result.scalars().all()
    db_data: dict[str, str] = {row.key: decrypt_config_value(row.value) for row in rows}
    static = get_static_settings()
    data: dict[str, str] = {}
    for key in ALLOWED_KEYS:
        val = db_data.get(key, "")
        if not val:
            val = str(getattr(static, key, "") or "")
        data[key] = _mask_secret(val) if key in SENSITIVE_KEYS else val
    return data


@router.get("", response_model=SettingsOut)
async def get_settings_api(
    _admin_id: str = Depends(_REQUIRE_PROVIDERS_MANAGE),
    db: AsyncSession = Depends(get_db),
):
    """读取全部 Provider 配置（敏感字段脱敏，合并 .env 回退值）"""
    return SettingsOut(settings=await _read_settings(db))


@router.put("", response_model=SettingsOut)
async def save_settings_api(
    body: SettingsIn,
    _admin_id: str = Depends(_REQUIRE_PROVIDERS_MANAGE),
    db: AsyncSession = Depends(get_db),
):
    """保存 Provider 配置（前端设置页提交）"""
    from sqlalchemy import select

    from app.core.dynamic_config import encrypt_config_value, invalidate_cache

    # 一次性加载现有配置（避免循环内逐条 SELECT）
    result = await db.execute(select(ProviderConfig))
    existing: dict[str, ProviderConfig] = {row.key: row for row in result.scalars().all()}

    saved: dict[str, str] = {}
    for key, value in body.settings.items():
        if key not in ALLOWED_KEYS:
            continue
        _validate_provider_setting(key, value)
        # 脱敏值不覆盖（前端回显的状态不写回）
        if key in SENSITIVE_KEYS and value == "configured":
            continue
        row = existing.get(key)
        stored_value = encrypt_config_value(value) if key in SENSITIVE_KEYS else value
        if row:
            row.value = stored_value
        else:
            db.add(ProviderConfig(key=key, value=stored_value))
        saved[key] = _mask_secret(value) if key in SENSITIVE_KEYS else value

    await db.commit()
    invalidate_cache()
    await write_audit(
        "provider_config_updated",
        user_id=_admin_id,
        detail="keys=" + ",".join(sorted(saved)),
    )
    return SettingsOut(settings=saved)


@provider_router.get("", response_model=SettingsOut)
async def get_providers_api(
    _admin_id: str = Depends(_REQUIRE_PROVIDERS_MANAGE),
    db: AsyncSession = Depends(get_db),
):
    return SettingsOut(settings=await _read_settings(db))


@provider_router.put("", response_model=SettingsOut)
async def save_providers_api(
    body: SettingsIn,
    _admin_id: str = Depends(_REQUIRE_PROVIDERS_MANAGE),
    db: AsyncSession = Depends(get_db),
):
    return await save_settings_api(body, _admin_id, db)
