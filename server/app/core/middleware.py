"""
TraceMiddleware（06 文档 §10.6.3）
- 从请求头提取/生成 X-Trace-Id
- 注入 contextvars 实现全链路贯通
- 响应头回传 trace_id 供前端关联
"""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from .logging import trace_id_var, user_id_var


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
