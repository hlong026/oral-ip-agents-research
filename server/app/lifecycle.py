"""应用生命周期：初始化运行依赖并恢复可继续执行的后台工作。"""

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings, validate_runtime_security
from app.core.db import SessionLocal, init_models, verify_migrations_current
from app.core.events import init_redis
from app.core.logging import get_logger

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """启动时恢复可恢复工作，关闭时停止发布心跳任务。"""
    logger = get_logger("oral")
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
    from app.modules.billing.repository import seed_prices
    from app.modules.catalog.service import seed_initial_price_catalog

    async with SessionLocal() as db:
        await seed_prices(db)
        await seed_initial_price_catalog(db)
        from app.modules.avatar.service import recover_unknown_submissions as recover_unknown_avatar_submissions
        from app.modules.content.jobs import recover_pending_jobs
        from app.modules.pipeline.service import recover_incomplete_tasks, recover_render_versions
        from app.modules.publish.service import recover_publish_jobs
        from app.modules.voice.service import recover_unknown_submissions as recover_unknown_voice_submissions
        from app.modules.webhook.service import recover_failed_webhooks

        await recover_pending_jobs(db)
        await recover_unknown_voice_submissions(db)
        await recover_unknown_avatar_submissions(db)
        await recover_incomplete_tasks(db)
        await recover_render_versions(db)
        await recover_publish_jobs(db)
        await recover_failed_webhooks(db)

    from app.providers.publish.heartbeat import start_heartbeat

    heartbeat_task = start_heartbeat()
    logger.info("oral-ip-agents server ready")
    try:
        yield
    finally:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)
