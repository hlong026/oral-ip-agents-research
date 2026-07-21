"""FastAPI 应用入口（模块化单体）
- 所有业务路由挂在 settings.api_prefix（默认 /api/v1）
- WS 网关 /ws/tasks；媒体文件 /media/{key}
- 启动：自动建表（开发）+ 事件总线 + 计费价目种子
- 日志：structlog 结构化输出（§10.6）
"""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings, validate_runtime_security
from app.core.db import SessionLocal, init_models, verify_migrations_current
from app.core.events import init_redis
from app.core.logging import get_logger, setup_logging
from app.core.middleware import TraceMiddleware
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
        from app.modules.pipeline.service import recover_incomplete_tasks
        from app.modules.publish.service import recover_publish_jobs

        await recover_incomplete_tasks(db)
        await recover_publish_jobs(db)
    if settings.im_enabled:
        from app.workers.im_listener import restore_listeners

        await restore_listeners()
    # 发布模块：启动 Cookie 心跳检测后台任务
    from app.providers.publish.heartbeat import start_heartbeat

    start_heartbeat()
    logger.info("oral-ip-agents server ready")
    yield
    if settings.im_enabled:
        from app.workers.im_listener import shutdown_all

        await shutdown_all()


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
                "message": str(exc)[:200] or "外部服务暂不可用，请稍后重试",
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_exc(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(f"unhandled: {request.method} {request.url.path}")
    # 生产环境不向客户端泄露内部错误详情
    msg = str(exc)[:200] if settings.app_env == "dev" else "服务器内部错误"
    return JSONResponse(status_code=500, content={"detail": {"code": "INTERNAL", "message": msg}})


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


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
for r in (auth_admin_router, activation_admin_router, catalog_admin_router, provider_router, admin_router):
    app.include_router(r, prefix="/api/admin/v1")
app.include_router(ws_router)

# ---- 媒体文件（本地存储驱动）----
os.makedirs(settings.local_storage_dir, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.local_storage_dir), name="media")
