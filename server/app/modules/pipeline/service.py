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
        schedule_run(task.id)
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


async def retry_step(db: AsyncSession, task_id: str, step: str, user_id: str) -> TaskOut:
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
    if t.reservation_id:
        from app.modules.billing.models import CreditReservation

        reservation = await db.get(CreditReservation, t.reservation_id)
        if reservation is None or reservation.status != "reserved":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "RETRY_REQUIRES_NEW_QUOTE",
                    "message": "原积分冻结已结束，请重新报价并创建任务",
                },
            )
    t.status = "pending"
    t.error = ""
    await repo.save(db, t)
    schedule_run(t.id, from_step=step)
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
    await repo.save(db, t)
    if idx + 1 < len(STEP_ORDER):
        schedule_run(t.id, from_step=STEP_ORDER[idx + 1])
    return to_out(t)


async def confirm(db: AsyncSession, task_id: str, user_id: str) -> TaskOut:
    """manual 模式逐步确认（waiting_confirm → 续跑下一步）"""
    t = await _must_get(db, task_id, user_id)
    if t.status != "waiting_confirm":
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "NOT_WAITING", "message": "任务不在待确认状态"})
    t.status = "pending"
    await repo.save(db, t)
    schedule_run(t.id)  # 不传 from_step：自动跳过已 done 步骤
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
        batchId=t.batch_id,
        createdAt=t.created_at.astimezone(UTC).isoformat(),
        updatedAt=t.updated_at.astimezone(UTC).isoformat(),
    )
