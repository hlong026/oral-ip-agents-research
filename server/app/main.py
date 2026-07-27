"""FastAPI 应用组合根：中间件、异常处理、健康探针和模块注册。"""

import asyncio

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.api.media import router as media_router
from app.api.routes import register_business_routes
from app.core import storage
from app.core.config import get_settings
from app.core.db import database_ready
from app.core.events import redis_ready
from app.core.logging import get_logger, setup_logging
from app.core.middleware import TraceMiddleware
from app.core.white_label import PUBLIC_PROVIDER_UNAVAILABLE, public_text
from app.lifecycle import lifespan
from app.providers.base import ProviderError

settings = get_settings()
setup_logging(settings.app_env)
logger = get_logger("oral")

app = FastAPI(title="口播IP智能体 API", version="1.0.0", lifespan=lifespan)
app.add_middleware(TraceMiddleware)
allowed_origins = (
    ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"]
    if settings.app_env == "dev"
    else [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Trace-Id"],
)


@app.exception_handler(ProviderError)
async def provider_exc(request: Request, exc: ProviderError) -> JSONResponse:
    logger.warning("provider_request_failed", method=request.method, path=request.url.path, error=str(exc)[:200])
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": {"code": "PROVIDER_UNAVAILABLE", "message": PUBLIC_PROVIDER_UNAVAILABLE}},
    )


@app.exception_handler(HTTPException)
async def http_exc(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if not request.url.path.startswith("/api/admin/v1"):
        if isinstance(detail, dict) and "message" in detail:
            detail = {**detail, "message": public_text(detail["message"])}
        elif isinstance(detail, str):
            detail = public_text(detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": detail}, headers=exc.headers)


@app.exception_handler(Exception)
async def unhandled_exc(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(f"unhandled: {request.method} {request.url.path}")
    message = public_text(exc, "服务器内部错误") if settings.app_env == "dev" else "服务器内部错误"
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": {"code": "INTERNAL", "message": message}},
    )


@app.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}


@app.get("/readyz")
async def readyz() -> Response:
    """生产就绪探针：验证实时依赖，并保留 Provider 配置快照。"""
    from app.providers.registry import registry

    has_mock = registry.has_mock_providers()
    database_ok, redis_ok, storage_ok = await asyncio.gather(
        database_ready(),
        redis_ready(),
        storage.storage_ready(),
    )
    redis_required = settings.app_env not in {"dev", "test"}
    ok = database_ok and storage_ok and (redis_ok or not redis_required)
    return JSONResponse(
        status_code=status.HTTP_200_OK if ok else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "ok": ok,
            "env": settings.app_env,
            "provider_mode": "mock_fallback" if has_mock else "real_only",
            "mock_fallback_allowed": settings.mock_fallback_allowed,
            "provider_chains": registry.chain_snapshot(),
            "dependencies": {
                "database": {"ok": database_ok, "required": True},
                "redis": {"ok": redis_ok, "required": redis_required},
                "storage": {"ok": storage_ok, "required": True},
            },
        },
    )


register_business_routes(app, api_prefix=settings.api_prefix, im_enabled=settings.im_enabled)
app.include_router(media_router)
