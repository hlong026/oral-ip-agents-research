"""voice 数据访问"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Voice


async def list_by_user(db: AsyncSession, user_id: str) -> list[Voice]:
    res = await db.execute(select(Voice).where(Voice.user_id == user_id).order_by(Voice.created_at.desc()))
    return list(res.scalars().all())


async def list_by_provider_voice_ids(db: AsyncSession, provider_voice_ids: list[str]) -> list[Voice]:
    """按供应商声音 ID 全库查询（云端找回去重：部署共用一个供应商账号，需跨用户比对）"""
    if not provider_voice_ids:
        return []
    res = await db.execute(select(Voice).where(Voice.provider_voice_id.in_(provider_voice_ids)))
    return list(res.scalars().all())


async def list_in_flight_clones(db: AsyncSession) -> list[Voice]:
    """全库查询克隆进行中的记录（provider_voice_id 尚未回填，云端找回按名称规避竞态导入）"""
    res = await db.execute(select(Voice).where(Voice.status.in_(("submitting", "training", "reconciliation_required"))))
    return list(res.scalars().all())


async def get(db: AsyncSession, voice_id: str, user_id: str | None = None) -> Voice | None:
    q = select(Voice).where(Voice.id == voice_id)
    if user_id:
        q = q.where(Voice.user_id == user_id)
    res = await db.execute(q)
    return res.scalar_one_or_none()


async def create(db: AsyncSession, **fields) -> Voice:
    v = Voice(**fields)
    db.add(v)
    await db.commit()
    await db.refresh(v)
    return v


async def delete(db: AsyncSession, voice: Voice) -> None:
    await db.delete(voice)
    await db.commit()
