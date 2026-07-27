"""pipeline 数据访问"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import PipelineTask


async def create(db: AsyncSession, **fields) -> PipelineTask:
    t = PipelineTask(**fields)
    db.add(t)
    await db.flush()
    await db.refresh(t)
    return t


async def get(db: AsyncSession, task_id: str, user_id: str | None = None) -> PipelineTask | None:
    q = select(PipelineTask).where(PipelineTask.id == task_id)
    if user_id:
        q = q.where(PipelineTask.user_id == user_id)
    res = await db.execute(q)
    return res.scalar_one_or_none()


async def save(db: AsyncSession, task: PipelineTask) -> PipelineTask:
    await db.commit()
    await db.refresh(task)
    return task


async def claim_for_run(db: AsyncSession, task_id: str) -> PipelineTask | None:
    """原子抢占待执行任务；重复消息只有一个消费者能进入流水线。"""
    result = await db.execute(
        update(PipelineTask)
        .where(PipelineTask.id == task_id, PipelineTask.status == "pending")
        .values(status="running", queue_message_id="")
        .execution_options(synchronize_session=False)
    )
    if int(getattr(result, "rowcount", 0) or 0) != 1:
        await db.rollback()
        return None
    await db.commit()
    return await get(db, task_id)


async def record_queue_message(db: AsyncSession, task_id: str, message_id: str) -> None:
    """仅在任务尚未被 Worker 抢占时记录消息号，避免回写过期队列状态。"""
    await db.execute(
        update(PipelineTask)
        .where(
            PipelineTask.id == task_id,
            PipelineTask.status == "pending",
            PipelineTask.queue_message_id == "",
        )
        .values(queue_message_id=message_id)
        .execution_options(synchronize_session=False)
    )
    await db.commit()


async def list_by_user(
    db: AsyncSession, user_id: str, status: str | None, page: int, page_size: int
) -> tuple[list[PipelineTask], int]:
    cond = PipelineTask.user_id == user_id
    if status:
        cond = cond & (PipelineTask.status == status)
    total = (await db.execute(select(func.count(PipelineTask.id)).where(cond))).scalar() or 0
    res = await db.execute(
        select(PipelineTask)
        .where(cond)
        .order_by(PipelineTask.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(res.scalars().all()), int(total)


async def stats(db: AsyncSession, user_id: str) -> dict:
    now = datetime.now(UTC)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    base = PipelineTask.user_id == user_id

    async def cnt(*conds) -> int:
        return int((await db.execute(select(func.count(PipelineTask.id)).where(base, *conds))).scalar() or 0)

    today_done = await cnt(PipelineTask.status == "done", PipelineTask.updated_at >= today)
    yesterday_done = await cnt(
        PipelineTask.status == "done",
        PipelineTask.updated_at >= today - timedelta(days=1),
        PipelineTask.updated_at < today,
    )
    queued = await cnt(PipelineTask.status.in_(["pending", "waiting_confirm"]))
    week_done = await cnt(PipelineTask.status == "done", PipelineTask.updated_at >= today - timedelta(days=7))
    prev_week = await cnt(
        PipelineTask.status == "done",
        PipelineTask.updated_at >= today - timedelta(days=14),
        PipelineTask.updated_at < today - timedelta(days=7),
    )
    failed = await cnt(PipelineTask.status.in_(["failed", "reconciliation_required"]))
    return {
        "todayDone": today_done,
        "todayDelta": today_done - yesterday_done,
        "queued": queued,
        "published": week_done,
        "weekDelta": week_done - prev_week,
        "pendingAlerts": failed,
    }


async def active_count(db: AsyncSession, user_id: str) -> int:
    return int(
        (
            await db.scalar(
                select(func.count(PipelineTask.id)).where(
                    PipelineTask.user_id == user_id,
                    PipelineTask.status.in_(["pending", "running", "waiting_confirm", "reconciliation_required"]),
                )
            )
        )
        or 0
    )


async def list_recoverable(db: AsyncSession) -> list[PipelineTask]:
    result = await db.execute(
        select(PipelineTask).where(
            (PipelineTask.status == "running")
            | ((PipelineTask.status == "pending") & (PipelineTask.queue_message_id == ""))
        )
    )
    return list(result.scalars().all())
