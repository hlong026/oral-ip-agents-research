"""pipeline 业务编排（F-405/406：批量扇出、单步重跑/覆盖、manual 确认）
日志：任务生命周期（§10.6.8-B #1）
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger

from . import repository as repo
from .engine import schedule_run
from .models import STEP_ORDER, PipelineTask
from .schemas import CreatePipelineIn, StatsOut, StepStateOut, TaskOut, TaskPageOut

logger = get_logger("oral.pipeline.service")
settings = get_settings()
_user_creation_locks: dict[str, asyncio.Lock] = {}


def _default_steps() -> list[dict]:
    return [
        {
            "step": s,
            "status": "pending",
            "progress": 0,
            "message": "",
            "compute": "cloud",
            "provider": "",
            "quotaCost": 0.0,
            "artifacts": {},
            "startedAt": None,
            "finishedAt": None,
            "durationMs": None,
        }
        for s in STEP_ORDER
    ]


async def create(db: AsyncSession, user_id: str, inp: CreatePipelineIn) -> list[TaskOut]:
    """同进程用轻量锁补齐 SQLite；生产数据库再用用户行锁跨进程串行化。"""
    lock = _user_creation_locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        return await _create_serialized(db, user_id, inp)


async def _create_serialized(db: AsyncSession, user_id: str, inp: CreatePipelineIn) -> list[TaskOut]:
    """创建任务；count>1 时批量扇出共享 batch_id（F-406）"""
    from app.modules.auth import repository as auth_repo

    user = await auth_repo.get_by_id_for_update(db, user_id)
    plan_expires_at = user.plan_expires_at if user else None
    if plan_expires_at and plan_expires_at.tzinfo is None:
        plan_expires_at = plan_expires_at.replace(tzinfo=UTC)
    if not user or not plan_expires_at or plan_expires_at <= datetime.now(UTC):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"code": "SUBSCRIPTION_REQUIRED", "message": "套餐未开通或已到期，请先激活或续费"},
        )
    if settings.app_env != "dev" and not inp.quoteId:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "QUOTE_REQUIRED", "message": "任务报价缺失，请重新计算积分后提交"},
        )
    if not (inp.sourceUrl or inp.topic or inp.scriptText):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INPUT_REQUIRED", "message": "链接/选题/文案至少填一项"},
        )
    count = max(1, min(inp.count, 20))
    from app.modules.activation import repository as activation_repo
    from app.modules.catalog import repository as catalog_repo

    subscriptions = await activation_repo.get_user_subscriptions(db, user_id)
    current_subscription = next((item for item in subscriptions if item.duration_days > 0), None)
    if current_subscription and current_subscription.sku_version_id:
        plan = await catalog_repo.get_plan_version(db, current_subscription.sku_version_id)
        if plan:
            active_tasks = await repo.active_count(db, user_id)
            if active_tasks + count > plan.max_concurrency:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    detail={
                        "code": "PLAN_CONCURRENCY_EXCEEDED",
                        "message": f"当前套餐最多允许 {plan.max_concurrency} 个并发任务",
                    },
                )
    batch_id = uuid.uuid4().hex[:12] if count > 1 else None
    title_src = (inp.topic or inp.scriptText or inp.sourceUrl or "未命名任务")[:24]
    tasks: list[PipelineTask] = []
    reservation_ids: list[str] = []
    if inp.quoteId:
        from app.modules.billing.service import reserve_quote
        from app.modules.ipasset import repository as ipasset_repo

        persona = await ipasset_repo.get(db, inp.ipId, user_id)
        task_for_quote = inp.model_dump()
        task_for_quote["_targetDurationSeconds"] = max(
            1,
            persona.video_duration if persona else 60,
        )

        reservation_batch = await reserve_quote(
            db,
            user_id,
            inp.quoteId,
            count,
            task_for_quote,
            commit=False,
        )
        reservation_ids = [item.id for item in reservation_batch.items]
    try:
        for i in range(count):
            title = f"{title_src} ·{i + 1}" if count > 1 else title_src
            t = await repo.create(
                db,
                user_id=user_id,
                ip_id=inp.ipId,
                title=title,
                source_url=inp.sourceUrl or "",
                topic=inp.topic or "",
                script_text=inp.scriptText or "",
                voice_id=inp.voiceId or "",
                avatar_id=inp.avatarId or "",
                platforms_json=json.dumps(inp.platforms, ensure_ascii=False),
                mode="manual" if inp.mode == "manual" else "auto",
                intensity=inp.intensity if inp.intensity in ("light", "structure", "theme") else "structure",
                randomize=inp.randomize or (count > 1),  # 批量默认开差异化随机化（C5）
                batch_id=batch_id,
                publish_at=inp.publishAt or "",
                steps_json=json.dumps(_default_steps(), ensure_ascii=False),
                reservation_id=reservation_ids[i] if reservation_ids else "",
            )
            if reservation_ids:
                from app.modules.billing.service import attach_reservation

                await attach_reservation(db, reservation_ids[i], user_id, t.id)
            tasks.append(t)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    for task in tasks:
        message_id = schedule_run(task.id)
        await repo.record_queue_message(db, task.id, message_id)
        await db.refresh(task)
    # 任务创建：记录 INFO（§10.6.8-B #1）
    logger.info(
        "task_created",
        user_id=user_id,
        task_id=tasks[0].id if tasks else "",
        mode=inp.mode or "auto",
        batch_size=count,
        source_type="url" if inp.sourceUrl else ("topic" if inp.topic else "script"),
    )
    return [to_out(t) for t in tasks]


async def list_tasks(db: AsyncSession, user_id: str, status_: str | None, page: int, page_size: int) -> TaskPageOut:
    items, total = await repo.list_by_user(db, user_id, status_, page, page_size)
    return TaskPageOut(items=[to_out(t) for t in items], total=total, page=page, pageSize=page_size)


async def get_task(db: AsyncSession, task_id: str, user_id: str) -> TaskOut:
    t = await _must_get(db, task_id, user_id)
    return to_out(t)


async def create_retry_quote(db: AsyncSession, task_id: str, user_id: str) -> dict:
    """基于服务端保存的原任务参数重建报价，避免前端漏报计费模块。"""
    from app.modules.billing.service import get_quota, pipeline_quote_quantities, save_quote
    from app.modules.catalog import repository as catalog_repo
    from app.modules.catalog.service import build_quote

    task = await _must_get(db, task_id, user_id)
    version = await catalog_repo.active_price_version(db)
    if version is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "NO_PRICE_VERSION", "message": "未发布价格版本"},
        )
    prices = await catalog_repo.module_prices(db, version.id)
    quantities = pipeline_quote_quantities(
        await _task_for_quote(db, task),
        {price.module: price.billing_unit for price in prices},
    )
    if not quantities:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "PRICE_NOT_FOUND", "message": "流水线价格配置不完整，暂时无法重试"},
        )
    quote = await build_quote(
        db,
        [{"module": module, "quantity": quantity} for module, quantity in quantities.items()],
    )
    catalog_version_id = str(quote.pop("_catalogVersionId"))
    await save_quote(db, user_id, quote, catalog_version_id)
    quote["availablePoints"] = (await get_quota(db, user_id)).balance
    return quote


async def retry_step(
    db: AsyncSession,
    task_id: str,
    step: str,
    user_id: str,
    quote_id: str | None = None,
) -> TaskOut:
    """单步重跑：重置该步及后续步骤，从断点续跑（F-405）"""
    _check_step(step)
    t = await _must_get(db, task_id, user_id)
    if t.status == "running":
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail={"code": "TASK_RUNNING", "message": "任务运行中，稍后再试"}
        )
    if t.status in {"done", "canceled"}:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "TASK_TERMINAL", "message": "已结束任务不可重试"},
        )
    needs_reservation = False
    if t.reservation_id:
        from app.modules.billing.models import CreditReservation

        reservation = await db.get(CreditReservation, t.reservation_id)
        if reservation is None or reservation.status != "reserved":
            needs_reservation = True
    elif settings.app_env != "dev":
        needs_reservation = True
    if needs_reservation:
        if not quote_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "RETRY_REQUIRES_NEW_QUOTE",
                    "message": "原积分冻结已结束，请重新报价后重试",
                },
            )
        from app.modules.billing.service import attach_reservation, reserve_quote

        batch = await reserve_quote(
            db,
            user_id,
            quote_id,
            task=await _task_for_quote(db, t),
            commit=False,
        )
        t.reservation_id = batch.items[0].id
        await attach_reservation(db, t.reservation_id, user_id, t.id)
    _clear_artifacts_from(t, step)
    t.status = "pending"
    t.error = ""
    t.queue_message_id = ""
    await repo.save(db, t)
    message_id = schedule_run(t.id, from_step=step)
    await repo.record_queue_message(db, t.id, message_id)
    await db.refresh(t)
    # 单步重跑：记录 INFO（§10.6.8-B #1）
    logger.info("task_retry", task_id=task_id, step=step, user_id=user_id)
    return to_out(t)


async def override_step(db: AsyncSession, task_id: str, step: str, user_id: str, artifacts: dict[str, str]) -> TaskOut:
    """人工覆盖：写入该步产物并标记完成，从下一步续跑（F-405 人工干预）"""
    _check_step(step)
    t = await _must_get(db, task_id, user_id)
    if t.status == "running":
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail={"code": "TASK_RUNNING", "message": "任务运行中，稍后再试"}
        )
    steps = json.loads(t.steps_json or "[]") or _default_steps()
    ctx = json.loads(t.artifacts_json or "{}")
    ctx.update(artifacts)
    idx = STEP_ORDER.index(step)
    now = datetime.now(UTC).isoformat()
    steps[idx].update(
        {
            "status": "done",
            "progress": 100,
            "message": "人工覆盖",
            "artifacts": {k: str(v)[:200] for k, v in artifacts.items()},
            "finishedAt": now,
        }
    )
    t.steps_json = json.dumps(steps, ensure_ascii=False)
    t.artifacts_json = json.dumps(ctx, ensure_ascii=False)
    t.status = "pending"
    t.error = ""
    t.queue_message_id = ""
    await repo.save(db, t)
    if idx + 1 < len(STEP_ORDER):
        message_id = schedule_run(t.id, from_step=STEP_ORDER[idx + 1])
        await repo.record_queue_message(db, t.id, message_id)
        await db.refresh(t)
    return to_out(t)


async def confirm(db: AsyncSession, task_id: str, user_id: str) -> TaskOut:
    """manual 模式逐步确认（waiting_confirm → 续跑下一步）"""
    t = await _must_get(db, task_id, user_id)
    if t.status != "waiting_confirm":
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "NOT_WAITING", "message": "任务不在待确认状态"})
    t.status = "pending"
    t.queue_message_id = ""
    await repo.save(db, t)
    message_id = schedule_run(t.id)
    await repo.record_queue_message(db, t.id, message_id)
    await db.refresh(t)
    # manual 确认：记录 INFO（§10.6.8-B #1）
    logger.info("task_confirmed", task_id=task_id, user_id=user_id)
    return to_out(t)


async def cancel(db: AsyncSession, task_id: str, user_id: str) -> TaskOut:
    t = await _must_get(db, task_id, user_id)
    if t.status in ("done", "failed", "canceled"):
        return to_out(t)
    t.status = "canceled"
    await repo.save(db, t)
    if t.reservation_id:
        from app.modules.billing.service import release_reservation

        await release_reservation(db, t.reservation_id, user_id)
    # 任务取消：记录 INFO（§10.6.8-B #1）
    logger.info("task_canceled", task_id=task_id, user_id=user_id)
    return to_out(t)


async def stats(db: AsyncSession, user_id: str) -> StatsOut:
    return StatsOut(**await repo.stats(db, user_id))


async def recover_incomplete_tasks(db: AsyncSession) -> int:
    """API 重启时补投安全步骤；结果未知的非幂等步骤禁止自动重放。"""
    tasks = await repo.list_recoverable(db)
    recoverable: list[tuple[PipelineTask, str | None]] = []
    for task in tasks:
        from_step = task.current_step or None if task.status == "running" else None
        artifacts = json.loads(task.artifacts_json or "{}")
        provider_result_unknown = task.status == "running" and (
            from_step == "voice" or (from_step == "avatar" and not artifacts.get("avatar_render_task_id"))
        )
        if provider_result_unknown:
            step_name = "语音" if from_step == "voice" else "数字人"
            task.status = "failed"
            task.queue_message_id = ""
            task.error = f"{from_step}: 供应商结果未知，为避免重复调用已停止自动恢复，请重新报价后重试"
            if task.reservation_id:
                from app.modules.billing.service import release_reservation

                await release_reservation(db, task.reservation_id, task.user_id)
            logger.error(
                "pipeline_recovery_requires_reconciliation",
                task_id=task.id,
                user_id=task.user_id,
                step=from_step,
            )
            from app.modules.notify.service import notify_user

            await notify_user(
                db,
                task.user_id,
                "error",
                f"任务需要人工确认：{task.title}",
                f"{step_name}供应商结果未知，为避免重复调用已停止自动恢复；请重新报价后从该步骤重试。",
            )
            continue
        task.status = "pending"
        task.queue_message_id = ""
        recoverable.append((task, from_step))
    if tasks:
        await db.commit()
    for task, from_step in recoverable:
        message_id = schedule_run(task.id, from_step)
        await repo.record_queue_message(db, task.id, message_id)
    if recoverable:
        logger.warning("pipeline_tasks_recovered", count=len(recoverable))
    return len(recoverable)


async def _task_for_quote(db: AsyncSession, task: PipelineTask) -> dict:
    from app.modules.ipasset import repository as ipasset_repo

    persona = await ipasset_repo.get(db, task.ip_id, task.user_id)
    return {
        "ipId": task.ip_id,
        "sourceUrl": task.source_url,
        "topic": task.topic,
        "scriptText": task.script_text,
        "voiceId": task.voice_id,
        "avatarId": task.avatar_id,
        "platforms": json.loads(task.platforms_json or "[]"),
        "_targetDurationSeconds": max(1, persona.video_duration if persona else 60),
    }


def _clear_artifacts_from(task: PipelineTask, step: str) -> None:
    """显式重试会清除该步及后续产物；重启恢复则保留供应商任务号。"""
    outputs = {
        "parse": {"video_key", "title", "platform"},
        "asr": {"transcript", "words"},
        "rewrite": {"script", "similarity", "topic_candidates"},
        "voice": {"audio_key", "tts_words", "duration"},
        "avatar": {"avatar_render_task_id", "avatar_provider", "avatar_video_key", "duration"},
        "compose": {"final_video_key", "cover_key", "quality", "duration"},
        "edit": {"edited"},
        "publish": {"publish_job_ids"},
    }
    artifacts = json.loads(task.artifacts_json or "{}")
    start = STEP_ORDER.index(step)
    for name in STEP_ORDER[start:]:
        for key in outputs[name]:
            artifacts.pop(key, None)
    task.artifacts_json = json.dumps(artifacts, ensure_ascii=False)


def _check_step(step: str) -> None:
    if step not in STEP_ORDER:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "BAD_STEP", "message": f"非法步骤：{step}"}
        )


async def _must_get(db: AsyncSession, task_id: str, user_id: str) -> PipelineTask:
    t = await repo.get(db, task_id, user_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "任务不存在"})
    return t


def to_out(t: PipelineTask) -> TaskOut:
    steps_raw = json.loads(t.steps_json or "[]") or _default_steps()
    ctx = json.loads(t.artifacts_json or "{}")
    cover = ctx.get("cover_key")
    return TaskOut(
        id=t.id,
        ipId=t.ip_id,
        title=t.title,
        coverUrl=f"/media/{cover}" if cover else None,
        sourceUrl=t.source_url,
        mode=t.mode,
        status=t.status,
        steps=[StepStateOut(**s) for s in steps_raw],
        currentStep=t.current_step or None,
        compute=t.compute,
        quotaCost=t.quota_cost,
        error=t.error,
        artifacts=ctx,
        batchId=t.batch_id,
        createdAt=t.created_at.astimezone(UTC).isoformat(),
        updatedAt=t.updated_at.astimezone(UTC).isoformat(),
    )
