"""
结构化日志基础设施（06 文档 §10.6.1-10.6.3）
- structlog + contextvars 实现请求级上下文注入
- trace_id / user_id / task_id 全链路贯通
- dev 环境彩色可读，prod 环境 JSON 输出
"""
import logging
from contextvars import ContextVar

import structlog

# ---- 请求级上下文变量 ----
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
user_id_var: ContextVar[str] = ContextVar("user_id", default="")
task_id_var: ContextVar[str] = ContextVar("task_id", default="")

# ---- 敏感字段脱敏规则（§10.6.5）----
_SENSITIVE_KEYS = {"password", "password_hash", "consent_token", "consenttoken",
                   "access_token", "accesstoken", "refresh_token", "refreshtoken",
                   "session_json", "api_key", "apikey", "authorization"}
_TRUNCATE_KEYS = {"source_url": 80, "script": 100, "text": 100, "original_text": 100}


def _inject_context(logger: logging.Logger, method_name: str, event_dict: dict) -> dict:
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


def _sanitize(logger: logging.Logger, method_name: str, event_dict: dict) -> dict:
    """敏感信息脱敏（§10.6.5）"""
    for key in list(event_dict.keys()):
        lower_key = key.lower().replace("-", "_")
        if lower_key in _SENSITIVE_KEYS:
            event_dict[key] = "***"
        elif lower_key in _TRUNCATE_KEYS:
            max_len = _TRUNCATE_KEYS[lower_key]
            val = event_dict[key]
            if isinstance(val, str) and len(val) > max_len:
                event_dict[key] = val[:max_len] + "..."
        # phone 脱敏：保留前3位 + ****
        elif lower_key == "phone" and isinstance(event_dict[key], str):
            phone = event_dict[key]
            if len(phone) >= 7:
                event_dict[key] = phone[:3] + "****" + phone[-4:]
    return event_dict


def setup_logging(app_env: str = "dev") -> None:
    """
    初始化 structlog 配置（在 main.py lifespan 之前调用）
    - dev: 彩色控制台输出
    - prod: JSON 格式（Docker json-file driver 采集）
    """
    # 渲染器选择
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


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """获取结构化 logger 实例"""
    return structlog.get_logger(name)
