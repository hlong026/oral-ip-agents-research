"""Provider 配置控制面。"""

import re
from typing import Literal, cast
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.db import get_db
from app.core.deps import require_admin
from app.core.logging import get_logger

from .models import ProviderConfig

router = APIRouter(prefix="/settings", tags=["settings"])
provider_router = APIRouter(prefix="/providers", tags=["admin-providers"])
logger = get_logger("oral.settings.providers")

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
    "feiying_api_key",
    "feiying_base_url",
    "feiying_enabled",
    "dashscope_enabled",
    "douyidou_enabled",
    "device_bind_limit",
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


class ProviderStatusItem(BaseModel):
    provider: str
    enabled: bool
    configured: bool
    missingFields: list[str]
    probeMode: Literal["credential", "sample"]


class ProviderStatusOut(BaseModel):
    items: list[ProviderStatusItem]


class ProviderProbeOut(BaseModel):
    provider: str
    status: Literal["verified", "failed", "incomplete", "needs_sample"]
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ProviderReadinessItem(BaseModel):
    provider: str
    enabled: bool
    configured: bool
    missingFields: list[str]
    ready: bool  # 开关已开 + 必填项齐全
    probeStatus: str = ""  # probe=true 时回填：verified | failed | incomplete | needs_sample
    probeMessage: str = ""


class ProviderReadinessOut(BaseModel):
    env: str
    providerMode: str  # real_only | mock_fallback
    mockFallbackAllowed: bool
    providerChains: dict[str, list[str]]
    items: list[ProviderReadinessItem]
    allReady: bool


_PROVIDER_REQUIREMENTS = {
    "deepseek": {
        "enabled": "deepseek_enabled",
        "required": (
            ("deepseek_api_key", "API Key"),
            ("deepseek_base_url", "Base URL"),
            ("deepseek_model", "模型"),
        ),
        "probe_mode": "credential",
    },
    "dashscope_asr": {
        "enabled": "dashscope_enabled",
        "required": (
            ("dashscope_api_key", "API Key"),
            ("dashscope_region", "地域"),
            ("asr_model", "异步模型"),
            ("asr_flash_model", "短音频同步模型"),
        ),
        "probe_mode": "credential",
    },
    "hifly": {
        "enabled": "feiying_enabled",
        "required": (
            ("feiying_api_key", "API Key"),
            ("feiying_base_url", "Base URL"),
        ),
        "probe_mode": "credential",
    },
    "douyidou": {
        "enabled": "douyidou_enabled",
        "required": (
            ("douyidou_app_id", "App ID"),
            ("douyidou_app_secret", "App Secret"),
            ("douyidou_base_url", "Base URL"),
        ),
        "probe_mode": "sample",
    },
}


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    return "configured"


def _validate_provider_setting(key: str, value: str) -> None:
    if key.endswith("_enabled") and value not in {"true", "false"}:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "PROVIDER_SETTING_INVALID", "message": f"{key} 必须是 true 或 false"},
        )
    if key == "dashscope_region" and value not in {"cn-beijing", "ap-southeast-1"}:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "PROVIDER_SETTING_INVALID", "message": "DashScope 地域无效"},
        )
    if key == "dashscope_workspace_id" and value and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "PROVIDER_SETTING_INVALID", "message": "DashScope Workspace ID 格式无效"},
        )
    if key in {"asr_model", "asr_flash_model"} and not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "PROVIDER_SETTING_INVALID", "message": f"{key} 格式无效"},
        )
    if key == "asr_flash_threshold_sec":
        try:
            threshold = int(value)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail={"code": "PROVIDER_SETTING_INVALID", "message": "ASR 分流阈值必须是整数"},
            ) from exc
        if not 1 <= threshold <= 3600:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail={"code": "PROVIDER_SETTING_INVALID", "message": "ASR 分流阈值必须在 1 到 3600 秒之间"},
            )
    if key == "device_bind_limit" and value:
        try:
            limit = int(value)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail={"code": "PROVIDER_SETTING_INVALID", "message": "设备绑定上限必须是整数"},
            ) from exc
        if not 1 <= limit <= 10:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail={"code": "PROVIDER_SETTING_INVALID", "message": "设备绑定上限必须在 1 到 10 之间"},
            )
    if not key.endswith("_base_url") or not value:
        return
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_BASE_URL_HOSTS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "PROVIDER_URL_NOT_ALLOWED", "message": "Provider 地址不在服务端白名单中"},
        )


async def _read_effective_settings(db: AsyncSession) -> dict[str, str]:
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
        data[key] = val
    return data


async def _read_settings(db: AsyncSession) -> dict[str, str]:
    data = await _read_effective_settings(db)
    return {key: _mask_secret(value) if key in SENSITIVE_KEYS else value for key, value in data.items()}


def _build_provider_status(provider: str, settings: dict[str, str]) -> ProviderStatusItem:
    spec = _PROVIDER_REQUIREMENTS[provider]
    missing = [label for key, label in spec["required"] if not settings.get(key, "").strip()]
    return ProviderStatusItem(
        provider=provider,
        enabled=settings.get(str(spec["enabled"])) == "true",
        configured=not missing,
        missingFields=missing,
        probeMode=cast(Literal["credential", "sample"], spec["probe_mode"]),
    )


def _probe_result(
    provider: str,
    status_value: Literal["verified", "failed", "incomplete", "needs_sample"],
    message: str,
    **details: object,
) -> ProviderProbeOut:
    return ProviderProbeOut(provider=provider, status=status_value, message=message, details=details)


async def _probe_provider(provider: str, settings: dict[str, str]) -> ProviderProbeOut:
    if provider not in _PROVIDER_REQUIREMENTS:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "PROVIDER_NOT_FOUND", "message": "未知 Provider"},
        )
    provider_status = _build_provider_status(provider, settings)
    if not provider_status.configured:
        return _probe_result(
            provider,
            "incomplete",
            "配置不完整：" + "、".join(provider_status.missingFields),
            missingFields=provider_status.missingFields,
        )
    if provider == "douyidou":
        return _probe_result(
            provider,
            "needs_sample",
            "配置项已完整；该服务需要真实样例链接才能验证签名和解析能力",
        )

    try:
        if provider == "deepseek":
            base_url = settings["deepseek_base_url"].rstrip("/")
            _validate_provider_setting("deepseek_base_url", base_url)
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                response = await client.get(
                    f"{base_url}/models",
                    headers={"Authorization": f"Bearer {settings['deepseek_api_key']}"},
                )
                response.raise_for_status()
            models = [
                item["id"]
                for item in response.json().get("data", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            ]
            selected_model = settings["deepseek_model"]
            if selected_model not in models:
                logger.warning(
                    "provider_probe_model_unavailable",
                    provider=provider,
                    selected_model=selected_model,
                )
                available = "、".join(models[:5]) or "无"
                return _probe_result(
                    provider,
                    "failed",
                    f"凭据有效，但配置模型 {selected_model} 不可用；可用模型：{available}",
                    models=models,
                    selectedModel=selected_model,
                )
            return _probe_result(
                provider,
                "verified",
                "凭据有效，配置模型可用",
                models=models,
                selectedModel=selected_model,
            )

        if provider == "dashscope_asr":
            workspace_id = settings.get("dashscope_workspace_id", "")
            region = settings["dashscope_region"]
            if workspace_id:
                base_url = f"https://{workspace_id}.{region}.maas.aliyuncs.com"
            else:
                base_url = {
                    "cn-beijing": "https://dashscope.aliyuncs.com",
                    "ap-southeast-1": "https://dashscope-intl.aliyuncs.com",
                }[region]
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                response = await client.get(
                    f"{base_url}/api/v1/files",
                    params={"page_no": 1, "page_size": 1},
                    headers={"Authorization": f"Bearer {settings['dashscope_api_key']}"},
                )
                response.raise_for_status()
            return _probe_result(
                provider,
                "verified",
                "凭据与区域端点连接正常；转写模型仍需使用真实音频验收",
                region=region,
                workspaceConfigured=bool(workspace_id),
            )

        base_url = settings["feiying_base_url"].rstrip("/")
        _validate_provider_setting("feiying_base_url", base_url)
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            response = await client.get(
                f"{base_url}/api/v2/hifly/account/credit",
                headers={"Authorization": f"Bearer {settings['feiying_api_key']}"},
            )
            response.raise_for_status()
        data = response.json()
        if data.get("code", 0) != 0:
            logger.warning("provider_probe_business_error", provider=provider, code=data.get("code"))
            return _probe_result(provider, "failed", "凭据校验失败，请检查 API Key")
        return _probe_result(
            provider,
            "verified",
            "凭据有效，账户连接正常",
            credits=data.get("left"),
        )
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        if isinstance(exc, httpx.HTTPStatusError):
            message = f"连接失败：供应商返回 HTTP {exc.response.status_code}"
        elif isinstance(exc, httpx.TimeoutException):
            message = "连接超时，请检查网络或供应商状态"
        else:
            message = f"连接失败：{str(exc)[:120]}"
        logger.warning("provider_probe_failed", provider=provider, error_type=type(exc).__name__)
        return _probe_result(provider, "failed", message)


@router.get("", response_model=SettingsOut)
async def get_settings_api(
    _admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """读取全部 Provider 配置（敏感字段脱敏，合并 .env 回退值）"""
    return SettingsOut(settings=await _read_settings(db))


@router.put("", response_model=SettingsOut)
async def save_settings_api(
    body: SettingsIn,
    _admin_id: str = Depends(require_admin),
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
    _admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return SettingsOut(settings=await _read_settings(db))


@provider_router.get("/status", response_model=ProviderStatusOut)
async def get_provider_status_api(
    _admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    settings = await _read_effective_settings(db)
    return ProviderStatusOut(items=[_build_provider_status(provider, settings) for provider in _PROVIDER_REQUIREMENTS])


@provider_router.get("/readiness", response_model=ProviderReadinessOut)
async def get_provider_readiness_api(
    probe: bool = False,
    _admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """供应商就绪度看板（切生产前人工核对清单）：
    逐项汇总 Key 配置/开关状态，probe=true 时附带连通性探测；同时暴露运行时 provider 链名单。
    """
    from app.core.config import get_settings as get_static_settings
    from app.providers.registry import registry

    effective = await _read_effective_settings(db)
    items: list[ProviderReadinessItem] = []
    for provider in _PROVIDER_REQUIREMENTS:
        st = _build_provider_status(provider, effective)
        item = ProviderReadinessItem(
            provider=provider,
            enabled=st.enabled,
            configured=st.configured,
            missingFields=st.missingFields,
            ready=st.enabled and st.configured,
        )
        if probe:
            probe_out = await _probe_provider(provider, effective)
            item.probeStatus = probe_out.status
            item.probeMessage = probe_out.message
            # 探测失败视为未就绪；needs_sample（douyidou）配置齐全即算就绪
            if probe_out.status == "failed":
                item.ready = False
        items.append(item)
    static = get_static_settings()
    has_mock = registry.has_mock_providers()
    return ProviderReadinessOut(
        env=static.app_env,
        providerMode="mock_fallback" if has_mock else "real_only",
        mockFallbackAllowed=static.mock_fallback_allowed,
        providerChains=registry.chain_snapshot(),
        items=items,
        allReady=all(item.ready for item in items),
    )


@provider_router.post("/{provider}/probe", response_model=ProviderProbeOut)
async def probe_provider_api(
    provider: str,
    admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await _probe_provider(provider, await _read_effective_settings(db))
    await write_audit(
        "provider_connection_probed",
        user_id=admin_id,
        detail=f"provider={provider},status={result.status}",
    )
    return result


@provider_router.put("", response_model=SettingsOut)
async def save_providers_api(
    body: SettingsIn,
    _admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await save_settings_api(body, _admin_id, db)
