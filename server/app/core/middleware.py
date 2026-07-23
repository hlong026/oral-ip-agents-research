"""
TraceMiddleware（06 文档 §10.6.3）
- 从请求头提取/生成 X-Trace-Id
- 注入 contextvars 实现全链路贯通
- 响应头回传 trace_id 供前端关联

AdminApiAllowlistMiddleware
- 管理控制面（/api/admin/*）网络层 IP/CIDR 白名单
- 白名单为空时不限制（仅推荐 dev/test）；生产由 validate_runtime_security 强制配置

resolve_client_ip（M1 修复：X-Forwarded-For 受信策略）
- 仅当直连对端属于 TRUSTED_PROXY_IPS 时采信 XFF 最左地址，否则一律使用直连对端 IP，
  防止公网直连场景下伪造 XFF 绕过白名单 / 登录频控 IP 主体
"""

import ipaddress
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .config import get_settings
from .logging import get_logger, trace_id_var, user_id_var

logger = get_logger("oral.middleware")


def _is_trusted_proxy(host: str) -> bool:
    """直连对端是否属于受信代理清单（TRUSTED_PROXY_IPS，逗号分隔 IP/CIDR）。"""
    allowlist = get_settings().trusted_proxy_ips
    if not allowlist.strip():
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    for entry in allowlist.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            if addr in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            logger.warning("trusted_proxy_invalid_entry", entry=entry)
    return False


def resolve_client_ip(request: Request) -> str:
    """解析客户端真实 IP。

    X-Forwarded-For 仅在直连对端属于受信代理（TRUSTED_PROXY_IPS）时采信最左地址；
    否则使用直连对端 IP。登录频控与管理面白名单必须统一走此函数，避免策略漂移。
    """
    direct = request.client.host if request.client else ""
    if direct and _is_trusted_proxy(direct):
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            candidate = forwarded.split(",")[0].strip()
            if candidate:
                return candidate
    return direct or "unknown"


class TraceMiddleware(BaseHTTPMiddleware):
    """请求级 trace_id 注入中间件"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # 从请求头提取或生成 trace_id
        tid = request.headers.get("X-Trace-Id") or uuid.uuid4().hex[:16]
        token = trace_id_var.set(tid)

        # 尝试从 JWT 解析 user_id（可选，auth 依赖会再次设置）
        user_id_var.set("")

        try:
            response = await call_next(request)
            # 响应头回传 trace_id
            response.headers["X-Trace-Id"] = tid
            return response
        finally:
            trace_id_var.reset(token)


class AdminApiAllowlistMiddleware(BaseHTTPMiddleware):
    """管理控制面（/api/admin/*）IP/CIDR 白名单。

    - 名单为空 = 不启用（dev/test 默认）；生产环境由 validate_runtime_security 强制配置。
    - 客户端 IP 经 resolve_client_ip 解析：仅受信代理（TRUSTED_PROXY_IPS）后的请求采信 XFF。
    """

    ADMIN_PATH_PREFIX = "/api/admin/"

    def __init__(self, app, allowed_networks: list[str] | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        for entry in allowed_networks or []:
            entry = entry.strip()
            if not entry:
                continue
            try:
                self._networks.append(ipaddress.ip_network(entry, strict=False))
            except ValueError:
                logger.warning("admin_allowlist_invalid_entry", entry=entry)

    @staticmethod
    def _client_ip(request: Request) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
        raw = resolve_client_ip(request)
        if not raw or raw == "unknown":
            return None
        try:
            return ipaddress.ip_address(raw)
        except ValueError:
            return None

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if self._networks and request.url.path.startswith(self.ADMIN_PATH_PREFIX):
            client_ip = self._client_ip(request)
            if client_ip is None or not any(client_ip in network for network in self._networks):
                logger.warning(
                    "admin_allowlist_rejected",
                    path=request.url.path,
                    client=str(client_ip) if client_ip else "unknown",
                )
                return JSONResponse(
                    status_code=403,
                    content={"detail": {"code": "ADMIN_IP_FORBIDDEN", "message": "当前网络无权访问管理控制台"}},
                )
        return await call_next(request)
