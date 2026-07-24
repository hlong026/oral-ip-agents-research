"""content 数据访问"""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ContentJob, Script, ScriptVersion


async def list_by_user(db: AsyncSession, user_id: str) -> list[Script]:
    res = await db.execute(select(Script).where(Script.user_id == user_id).order_by(Script.created_at.desc()))
    return list(res.scalars().all())


async def get(db: AsyncSession, script_id: str, user_id: str) -> Script | None:
    res = await db.execute(select(Script).where(Script.id == script_id, Script.user_id == user_id))
    return res.scalar_one_or_none()


async def create(db: AsyncSession, **fields) -> Script:
    s = Script(**fields)
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def save(db: AsyncSession, script: Script) -> Script:
    await db.commit()
    await db.refresh(script)
    return script


async def append_version(
    db: AsyncSession,
    script: Script,
    *,
    kind: str,
    text: str,
    model_name: str,
    prompt_version: str,
) -> ScriptVersion:
    version = ScriptVersion(
        script_id=script.id,
        user_id=script.user_id,
        version=script.current_version,
        kind=kind,
        text=text,
        model_name=model_name,
        prompt_version=prompt_version,
    )
    db.add(version)
    await db.commit()
    await db.refresh(version)
    return version


async def list_versions(db: AsyncSession, script_id: str, user_id: str) -> list[ScriptVersion]:
    result = await db.execute(
        select(ScriptVersion)
        .where(ScriptVersion.script_id == script_id, ScriptVersion.user_id == user_id)
        .order_by(ScriptVersion.version)
    )
    return list(result.scalars().all())


async def create_job(db: AsyncSession, **fields) -> ContentJob:
    job = ContentJob(**fields)
    db.add(job)
    await db.flush()
    return job


async def get_job(db: AsyncSession, job_id: str, user_id: str | None = None) -> ContentJob | None:
    query = select(ContentJob).where(ContentJob.id == job_id)
    if user_id is not None:
        query = query.where(ContentJob.user_id == user_id)
    return (await db.execute(query)).scalar_one_or_none()


async def claim_job(db: AsyncSession, job_id: str) -> ContentJob | None:
    claimed = await db.execute(
        update(ContentJob)
        .where(ContentJob.id == job_id, ContentJob.status == "pending")
        .values(status="running", progress=5, stage="任务已进入后台队列")
    )
    if int(getattr(claimed, "rowcount", 0) or 0) != 1:
        await db.rollback()
        return None
    await db.commit()
    return await get_job(db, job_id)


async def record_job_message(db: AsyncSession, job_id: str, message_id: str) -> None:
    await db.execute(update(ContentJob).where(ContentJob.id == job_id).values(queue_message_id=message_id))
    await db.commit()


async def pending_jobs(db: AsyncSession) -> list[ContentJob]:
    result = await db.execute(select(ContentJob).where(ContentJob.status == "pending"))
    return list(result.scalars().all())
