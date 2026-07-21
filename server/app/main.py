"""FastAPI 应用入口（模块化单体）
- 所有业务路由挂在 settings.api_prefix（默认 /api/v1）
- WS 网关 /ws/tasks；媒体文件 /media/{key}
- 启动：自动建表（开发）+ 事件总线 + 计费价目种子
- 日志：structlog 结构化输出（§10.6）
"""

import os
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from mimetypes import guess_type
from typing import Annotated, Any

from botocore.exceptions import ClientError
from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

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
    return {"ok": True, "storage": settings.storage_driver}


@app.get("/readyz")
async def readyz() -> dict:
    from sqlalchemy import text

    from app.core.events import redis_ready
    from app.core.storage import storage_ready

    database_ok = False
    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
        database_ok = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("database_readiness_failed", error=str(exc)[:160])
    redis_ok = await redis_ready()
    storage_ok = await storage_ready()
    state = {
        "database": database_ok,
        "redis": redis_ok,
        "storage": storage_ok,
    }
    if not all(state.values()):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "NOT_READY", **state},
        )
    return {"ok": True, **state}


def _stream_s3_body(body: Any) -> Iterator[bytes]:
    try:
        yield from body.iter_chunks(chunk_size=1024 * 1024)
    finally:
        body.close()


@app.get(
    "/media/{key:path}",
    responses={
        200: {
            "description": "完整媒体文件",
            "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
        },
        206: {
            "description": "媒体字节范围",
            "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
        },
        404: {"description": "媒体文件不存在"},
        416: {"description": "媒体范围无效"},
        503: {"description": "媒体存储暂不可用"},
    },
)
async def media_file(
    key: str,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
):
    """Serve local files or proxy S3 ranges through the stable /media contract."""
    from app.core.storage import get_object, local_path

    if settings.storage_driver == "local":
        try:
            path = local_path(key)
        except ValueError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "媒体文件不存在") from exc
        if not path.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "媒体文件不存在")
        return FileResponse(path)

    try:
        obj = await get_object(key, range_header)
    except ClientError as exc:
        error_code = str(exc.response.get("Error", {}).get("Code", ""))
        http_status = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 503))
        if error_code in {"NoSuchKey", "NotFound", "404"} or http_status == 404:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "媒体文件不存在") from exc
        if http_status == 416:
            raise HTTPException(status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE, "媒体范围无效") from exc
        logger.warning("media_s3_read_failed", key=key, status=http_status, error=error_code)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "媒体存储暂不可用") from exc
    except Exception as exc:
        logger.warning("media_s3_read_failed", key=key, error=str(exc)[:160])
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "媒体存储暂不可用") from exc

    headers = {"Accept-Ranges": "bytes"}
    if content_range := obj.get("ContentRange"):
        headers["Content-Range"] = str(content_range)
    if content_length := obj.get("ContentLength"):
        headers["Content-Length"] = str(content_length)
    if etag := obj.get("ETag"):
        headers["ETag"] = str(etag)
    media_type = str(obj.get("ContentType") or guess_type(key)[0] or "application/octet-stream")
    return StreamingResponse(
        _stream_s3_body(obj["Body"]),
        status_code=status.HTTP_206_PARTIAL_CONTENT if obj.get("ContentRange") else status.HTTP_200_OK,
        headers=headers,
        media_type=media_type,
    )


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
