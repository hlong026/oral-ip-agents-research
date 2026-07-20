"""voice 数据访问"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Voice


async def list_by_user(db: AsyncSession, user_id: str) -> list[Voice]:
    res = await db.execute(select(Voice).where(Voice.user_id == user_id).order_by(Voice.created_at.desc()))
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
