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

from app.core.config import get_settings
from app.core.db import SessionLocal, init_models
from app.core.events import init_redis
from app.core.logging import get_logger, setup_logging
from app.core.middleware import TraceMiddleware

settings = get_settings()
setup_logging(settings.app_env)  # 初始化 structlog（必须在其他模块加载前）
logger = get_logger("oral")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    os.makedirs(settings.local_storage_dir, exist_ok=True)
    await init_models()
    await init_redis(settings.redis_url)
    # 计费价目种子（quota_price 表）
    from app.modules.billing.repository import seed_prices

    async with SessionLocal() as db:
        await seed_prices(db)
    # #7 恢复 IM 监听
    from app.workers.im_listener import restore_listeners
    await restore_listeners()
    logger.info("oral-ip-agents server ready")
    yield
    # #7 shutdown 清理 IM 监听
    from app.workers.im_listener import shutdown_all
    await shutdown_all()


app = FastAPI(title="口播IP智能体 API", version="1.0.0", lifespan=lifespan)

# TraceMiddleware 必须在 CORS 之前添加（确保 trace_id 注入）
app.add_middleware(TraceMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Trace-Id"],  # 允许前端读取 trace_id
)


@app.exception_handler(Exception)
async def unhandled_exc(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(f"unhandled: {request.method} {request.url.path}")
    return JSONResponse(status_code=500,
                        content={"detail": {"code": "INTERNAL", "message": str(exc)[:200]}})


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


# ---- 业务路由 ----
from app.modules.auth.router import router as auth_router  # noqa: E402
from app.modules.avatar.router import router as avatar_router  # noqa: E402
from app.modules.billing.router import router as billing_router  # noqa: E402
from app.modules.content.router import router as content_router  # noqa: E402
from app.modules.dashboard.router import router as dashboard_router  # noqa: E402
from app.modules.ipasset.router import router as ipasset_router  # noqa: E402
from app.modules.notify.router import router as notify_router  # noqa: E402
from app.modules.notify.ws import ws_router  # noqa: E402
from app.modules.pipeline.router import router as pipeline_router  # noqa: E402
from app.modules.im.router import router as im_router  # noqa: E402
from app.modules.publish.router import router as publish_router  # noqa: E402
from app.modules.settings.router import router as settings_router  # noqa: E402
from app.modules.voice.router import router as voice_router  # noqa: E402
from app.modules.webhook.router import router as webhook_router  # noqa: E402

for r in (auth_router, billing_router, ipasset_router, voice_router, avatar_router,
          content_router, pipeline_router, publish_router, im_router, notify_router,
          dashboard_router, webhook_router, settings_router):
    app.include_router(r, prefix=settings.api_prefix)
app.include_router(ws_router)

# ---- 媒体文件（本地存储驱动）----
os.makedirs(settings.local_storage_dir, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.local_storage_dir), name="media")
