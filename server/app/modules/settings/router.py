"""settings HTTP 层：Provider 配置读写（前端设置页调用）"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user_id

from .models import ProviderConfig

router = APIRouter(prefix="/settings", tags=["settings"])

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
    "feiying_api_key",
    "feiying_base_url",
}

# 敏感 key（GET 时脱敏返回）
SENSITIVE_KEYS = {
    "douyidou_app_secret",
    "dashscope_api_key",
    "deepseek_api_key",
    "feiying_api_key",
}


class SettingsOut(BaseModel):
    settings: dict[str, str]


class SettingsIn(BaseModel):
    settings: dict[str, str]


@router.get("", response_model=SettingsOut)
async def get_settings_api(
    _user: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """读取全部 Provider 配置（敏感字段脱敏，合并 .env 回退值）"""
    from sqlalchemy import select

    from app.core.config import get_settings as get_static_settings

    result = await db.execute(select(ProviderConfig))
    rows = result.scalars().all()
    db_data: dict[str, str] = {row.key: row.value for row in rows}

    # 合并 .env 回退值（DB 无值时显示 .env 中的配置）
    static = get_static_settings()
    data: dict[str, str] = {}
    for key in ALLOWED_KEYS:
        val = db_data.get(key, "")
        if not val:
            val = str(getattr(static, key, "") or "")
        if key in SENSITIVE_KEYS and val:
            # 脱敏：只显示前4位 + 掩码
            data[key] = val[:4] + "•" * 20 if len(val) > 4 else "•" * 8
        else:
            data[key] = val
    return SettingsOut(settings=data)


@router.put("", response_model=SettingsOut)
async def save_settings_api(
    body: SettingsIn,
    _user: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """保存 Provider 配置（前端设置页提交）"""
    from sqlalchemy import select

    from app.core.dynamic_config import invalidate_cache

    # 一次性加载现有配置（避免循环内逐条 SELECT）
    result = await db.execute(select(ProviderConfig))
    existing: dict[str, ProviderConfig] = {row.key: row for row in result.scalars().all()}

    saved: dict[str, str] = {}
    for key, value in body.settings.items():
        if key not in ALLOWED_KEYS:
            continue
        # 脱敏值不覆盖（前端回显的掩码不写回）
        if key in SENSITIVE_KEYS and value and "•" in value:
            continue
        row = existing.get(key)
        if row:
            row.value = value
        else:
            db.add(ProviderConfig(key=key, value=value))
        saved[key] = value

    await db.commit()
    invalidate_cache()
    return SettingsOut(settings=saved)
