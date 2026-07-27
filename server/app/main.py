"""FastAPI 应用入口（模块化单体）
- 所有业务路由挂在 settings.api_prefix（默认 /api/v1）
- WS 网关 /ws/tasks；媒体文件 /media/{key}
- 启动：自动建表（开发）+ 事件总线 + 计费价目种子
- 日志：structlog 结构化输出（§10.6）
"""

import mimetypes
import os
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.core import storage
from app.core.config import get_settings, validate_runtime_security
from app.core.db import SessionLocal, init_models, verify_migrations_current
from app.core.events import init_redis
from app.core.logging import get_logger, setup_logging
from app.core.middleware import TraceMiddleware
from app.core.white_label import PUBLIC_PROVIDER_UNAVAILABLE, public_text
from app.providers.base import ProviderError

settings = get_settings()
setup_logging(settings.app_env)  # 初始化 structlog（必须在其他模块加载前）
logger = get_logger("oral")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    validate_runtime_security(settings)
    os.makedirs(settings.local_storage_dir, exist_ok=True)
    if settings.app_env in {"dev", "test"}:
        await init_models()
    else:
        await verify_migrations_current()
    from app.core.bootstrap import ensure_bootstrap_admin
    from app.modules.publish.repository import migrate_plaintext_sessions

    async with SessionLocal() as db:
        await ensure_bootstrap_admin(db, settings)
        migrated_sessions = await migrate_plaintext_sessions(db)
        if migrated_sessions:
            logger.warning("publish_sessions_encrypted", count=migrated_sessions)
    await init_redis(settings.redis_url)
    # 计费价目种子（quota_price 表）
    from app.modules.billing.repository import seed_prices
    from app.modules.catalog.service import seed_initial_price_catalog

    async with SessionLocal() as db:
        await seed_prices(db)
        await seed_initial_price_catalog(db)
        from app.modules.content.jobs import recover_pending_jobs
        from app.modules.pipeline.service import recover_incomplete_tasks
        from app.modules.publish.service import recover_publish_jobs

        await recover_pending_jobs(db)
        await recover_incomplete_tasks(db)
        await recover_publish_jobs(db)
    # 发布模块：启动 Cookie 心跳检测后台任务
    from app.providers.publish.heartbeat import start_heartbeat

    start_heartbeat()
    logger.info("oral-ip-agents server ready")
    yield


app = FastAPI(title="口播IP智能体 API", version="1.0.0", lifespan=lifespan)

# TraceMiddleware 必须在 CORS 之前添加（确保 trace_id 注入）
app.add_middleware(TraceMiddleware)
_allowed_origins = (
    ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"]
    if settings.app_env == "dev"
    else [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
)
if not _allowed_origins and settings.app_env != "dev":
    import warnings

    warnings.warn("CORS_ORIGINS 未配置，生产环境跨域请求将被拒绝", stacklevel=1)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Trace-Id"],  # 允许前端读取 trace_id
)


@app.exception_handler(ProviderError)
async def provider_exc(request: Request, exc: ProviderError) -> JSONResponse:
    logger.warning("provider_request_failed", method=request.method, path=request.url.path, error=str(exc)[:200])
    return JSONResponse(
        status_code=503,
        content={
            "detail": {
                "code": "PROVIDER_UNAVAILABLE",
                "message": PUBLIC_PROVIDER_UNAVAILABLE,
            }
        },
    )


@app.exception_handler(HTTPException)
async def http_exc(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if not request.url.path.startswith("/api/admin/v1"):
        if isinstance(detail, dict) and "message" in detail:
            detail = {**detail, "message": public_text(detail["message"])}
        elif isinstance(detail, str):
            detail = public_text(detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": detail},
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def unhandled_exc(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(f"unhandled: {request.method} {request.url.path}")
    # 生产环境不向客户端泄露内部错误详情
    msg = public_text(exc, "服务器内部错误") if settings.app_env == "dev" else "服务器内部错误"
    return JSONResponse(status_code=500, content={"detail": {"code": "INTERNAL", "message": msg}})


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.get("/readyz")
async def readyz() -> dict:
    """部署验证端点：暴露运行环境、provider 模式与各链名单，切生产后用于确认零 Mock"""
    from app.providers.registry import registry

    has_mock = registry.has_mock_providers()
    return {
        "ok": True,
        "env": settings.app_env,
        "provider_mode": "mock_fallback" if has_mock else "real_only",
        "mock_fallback_allowed": settings.mock_fallback_allowed,
        "provider_chains": registry.chain_snapshot(),
    }


# ---- 业务路由 ----
from app.modules.activation.router import admin_router as activation_admin_router  # noqa: E402
from app.modules.activation.router import router as activation_router  # noqa: E402
from app.modules.activation.router import subscription_router  # noqa: E402
from app.modules.admin.router import router as admin_router  # noqa: E402
from app.modules.auth.router import admin_router as auth_admin_router  # noqa: E402
from app.modules.auth.router import router as auth_router  # noqa: E402
from app.modules.avatar.router import router as avatar_router  # noqa: E402
from app.modules.billing.router import router as billing_router  # noqa: E402
from app.modules.catalog.router import admin_router as catalog_admin_router  # noqa: E402
from app.modules.catalog.router import router as catalog_router  # noqa: E402
from app.modules.content.router import router as content_router  # noqa: E402
from app.modules.dashboard.router import router as dashboard_router  # noqa: E402
from app.modules.im.router import admin_router as im_admin_router  # noqa: E402
from app.modules.im.router import router as im_router  # noqa: E402
from app.modules.ipasset.router import router as ipasset_router  # noqa: E402
from app.modules.notify.router import router as notify_router  # noqa: E402
from app.modules.notify.ws import ws_router  # noqa: E402
from app.modules.pipeline.router import router as pipeline_router  # noqa: E402
from app.modules.publish.router import router as publish_router  # noqa: E402
from app.modules.settings.router import provider_router  # noqa: E402
from app.modules.voice.router import router as voice_router  # noqa: E402
from app.modules.webhook.router import router as webhook_router  # noqa: E402

user_routers = (
    auth_router,
    activation_router,
    subscription_router,
    billing_router,
    catalog_router,
    ipasset_router,
    voice_router,
    avatar_router,
    content_router,
    pipeline_router,
    publish_router,
    notify_router,
    dashboard_router,
    webhook_router,
)
for r in user_routers:
    app.include_router(r, prefix=settings.api_prefix)
if settings.im_enabled:
    app.include_router(im_router, prefix=settings.api_prefix)
admin_routers = (
    auth_admin_router,
    activation_admin_router,
    catalog_admin_router,
    provider_router,
    admin_router,
    im_admin_router,
)
for r in admin_routers:
    app.include_router(r, prefix="/api/admin/v1")
app.include_router(ws_router)


# ---- 媒体文件（统一读取 local / s3 存储驱动）----
_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")


@app.head("/media/{key:path}", include_in_schema=False)
@app.get("/media/{key:path}", name="media")
async def media_file(key: str, request: Request) -> Response:
    try:
        total = await storage.size(key)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "媒体文件不存在") from exc
    content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
    headers = {"accept-ranges": "bytes"}

    # Range 支持：Safari 播放视频强依赖 206，拖进度条也靠它避免重新全量下载
    start, end, response_status = 0, total - 1, status.HTTP_200_OK
    range_header = request.headers.get("range")
    m = _RANGE_RE.match(range_header.strip()) if range_header else None
    if m:  # 语法不匹配（多区间/未知单位）按 RFC 9110 忽略该头，回落 200 全量
        spec_start, spec_end = m.group(1), m.group(2)
        if spec_start:
            start = int(spec_start)
            end = min(int(spec_end), total - 1) if spec_end else total - 1
        elif spec_end:  # 后缀区间 bytes=-N：最后 N 字节
            start = max(total - int(spec_end), 0)
            end = total - 1
        if (not spec_start and not spec_end) or start > end or start >= total:
            return Response(
                status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
                headers={"content-range": f"bytes */{total}"},
            )
        response_status = status.HTTP_206_PARTIAL_CONTENT
        headers["content-range"] = f"bytes {start}-{end}/{total}"

    headers["content-length"] = str(max(end - start + 1, 0))
    # 空文件短路：s3 分支对 bytes=0--1 会报 InvalidRange，且流中途抛错时响应头已发出
    if request.method == "HEAD" or total == 0:
        return Response(status_code=response_status, headers=headers, media_type=content_type)
    return StreamingResponse(
        storage.stream_range(key, start, end),
        status_code=response_status,
        headers=headers,
        media_type=content_type,
    )
