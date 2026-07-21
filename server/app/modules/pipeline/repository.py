"""pipeline 数据访问"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
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
    failed = await cnt(PipelineTask.status == "failed")
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
                    PipelineTask.status.in_(["pending", "running", "waiting_confirm"]),
                )
            )
        )
        or 0
    )
