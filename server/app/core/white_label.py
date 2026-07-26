"""面向用户输出的供应商白标化工具。"""

import re
from typing import Any

from fastapi import HTTPException

from app.providers.base import ProviderError

PUBLIC_PROVIDER_UNAVAILABLE = "外部服务暂不可用，请稍后重试"
PUBLIC_PROCESSING_FAILED = "处理失败，请稍后重试"
PUBLIC_MODEL_NAME = "智能文案引擎"

_PROVIDER_BRANDS = (
    "minimax",
    "speech-02",
    "hifly",
    "飞影",
    "dashscope",
    "阿里云",
    "aliyun",
    "douyidou",
    "deepseek",
    "豆包",
    "云雾",
    "cosyvoice",
    "gpt-sovits",
    "fun-asr",
    "whisper",
    "heygem",
    "ffmpeg",
    "redis",
)


def contains_provider_brand(value: object) -> bool:
    text = str(value).casefold()
    return any(brand.casefold() in text for brand in _PROVIDER_BRANDS)


def redact_provider_brands(value: object) -> str:
    text = str(value or "")
    for brand in sorted(_PROVIDER_BRANDS, key=len, reverse=True):
        text = re.sub(re.escape(brand), "外部服务", text, flags=re.IGNORECASE)
    return text[:500]


def public_text(value: object, fallback: str = PUBLIC_PROCESSING_FAILED) -> str:
    text = str(value or "").strip()
    if not text or contains_provider_brand(text):
        return fallback
    return text[:500]


def public_error_message(
    exc: BaseException,
    fallback: str = PUBLIC_PROCESSING_FAILED,
) -> str:
    if isinstance(exc, ProviderError):
        return PUBLIC_PROVIDER_UNAVAILABLE
    if isinstance(exc, HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("code") or fallback
        return public_text(detail, fallback)
    return fallback


def public_model_name(model_name: str) -> str:
    if model_name in {"source", "human"}:
        return model_name
    return PUBLIC_MODEL_NAME


def public_metadata(value: Any, *, redact_values: bool = False) -> Any:
    """清理系统产物元数据；正文内容不应通过此函数处理。"""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = key.casefold()
            if normalized_key in {"providername", "provider_name", "modelname", "model_name"}:
                cleaned[key] = public_model_name(str(item))
                continue
            if "provider" in normalized_key:
                continue
            cleaned_item = public_metadata(item, redact_values=redact_values)
            if isinstance(cleaned_item, str) and not cleaned_item and item:
                continue
            cleaned[key] = cleaned_item
        return cleaned
    if isinstance(value, list):
        return [public_metadata(item, redact_values=redact_values) for item in value]
    if isinstance(value, tuple):
        return tuple(public_metadata(item, redact_values=redact_values) for item in value)
    if redact_values and isinstance(value, str) and contains_provider_brand(value):
        return ""
    return value
