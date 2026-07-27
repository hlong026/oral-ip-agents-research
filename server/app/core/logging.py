"""
结构化日志基础设施（06 文档 §10.6.1-10.6.3）
- structlog + contextvars 实现请求级上下文注入
- trace_id / user_id / task_id 全链路贯通
- dev 环境彩色可读，prod 环境 JSON 输出
"""

import logging
import re
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any

import structlog

# ---- 请求级上下文变量 ----
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
user_id_var: ContextVar[str] = ContextVar("user_id", default="")
task_id_var: ContextVar[str] = ContextVar("task_id", default="")

# ---- 敏感字段脱敏规则（§10.6.5）----
_SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "consent_token",
    "consenttoken",
    "access_token",
    "accesstoken",
    "refresh_token",
    "refreshtoken",
    "session_json",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "cookies",
    "publish_session_encryption_key",
    "s3_secret_key",
    "secret",
    "secret_key",
    "signature",
    "token",
}
_TRUNCATE_KEYS = {"source_url": 80, "script": 100, "text": 100, "original_text": 100}
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:authorization|api[_-]?key|access[_-]?token|refresh[_-]?token|token|"
    r"signature|x-amz-credential|x-amz-security-token|cookie|sessionid(?:_ss)?|"
    r"password|secret)\b[\"']?\s*[:=]\s*(?:bearer\s+)?[\"']?)[^&,\s;\"']+"
)
_BEARER_RE = re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/=-]+")
_PHONE_RE = re.compile(r"(?<!\d)(1\d{10})(?!\d)")


def sanitize_text(value: str) -> str:
    """Redact credentials, signed query values and mainland phone numbers in free-form text."""

    redacted = _SECRET_ASSIGNMENT_RE.sub(r"\1***", value)
    redacted = _BEARER_RE.sub(r"\1***", redacted)
    return _PHONE_RE.sub(lambda match: match.group(1)[:3] + "****" + match.group(1)[-4:], redacted)


def sanitize_loguru_record(record: MutableMapping[str, Any]) -> bool:
    """Sanitize vendor loguru records and suppress their unredacted traceback payload."""

    record["message"] = sanitize_text(str(record.get("message", "")))
    record["exception"] = None
    return True


class SensitiveDataFilter(logging.Filter):
    """Apply the same redaction boundary to standard-library and vendor logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        parts = [sanitize_text(record.getMessage())]
        if record.exc_info:
            parts.append(sanitize_text(logging.Formatter().formatException(record.exc_info)))
        if record.stack_info:
            parts.append(sanitize_text(record.stack_info))
        record.msg = "\n".join(parts)
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


def _inject_context(_logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """注入 contextvars 中的 trace_id / user_id / task_id"""
    tid = trace_id_var.get()
    uid = user_id_var.get()
    task = task_id_var.get()
    if tid:
        event_dict.setdefault("trace_id", tid)
    if uid:
        event_dict.setdefault("user_id", uid)
    if task:
        event_dict.setdefault("task_id", task)
    return event_dict


def _sanitize(_logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """敏感信息脱敏（§10.6.5）"""
    for key in list(event_dict.keys()):
        lower_key = key.lower().replace("-", "_")
        if lower_key in _SENSITIVE_KEYS:
            event_dict[key] = "***"
        # phone 脱敏：保留前3位 + ****
        elif lower_key == "phone" and isinstance(event_dict[key], str):
            phone = event_dict[key]
            if len(phone) >= 7:
                event_dict[key] = phone[:3] + "****" + phone[-4:]
        elif isinstance(event_dict[key], str):
            value = sanitize_text(event_dict[key])
            max_len = _TRUNCATE_KEYS.get(lower_key)
            if max_len and len(value) > max_len:
                value = value[:max_len] + "..."
            event_dict[key] = value
    return event_dict


def setup_logging(app_env: str = "dev") -> None:
    """
    初始化 structlog 配置（在 main.py lifespan 之前调用）
    - dev: 彩色控制台输出
    - prod: JSON 格式（Docker json-file driver 采集）
    """
    # 渲染器选择
    renderer: Any
    if app_env == "dev":
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _inject_context,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _sanitize,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # 同步配置标准库 logging（兼容第三方库日志）
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    for handler in logging.getLogger().handlers:
        handler.addFilter(SensitiveDataFilter())


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """获取结构化 logger 实例"""
    return structlog.get_logger(name)
