"""avatar 数据访问"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Avatar


async def list_by_user(db: AsyncSession, user_id: str) -> list[Avatar]:
    res = await db.execute(select(Avatar).where(Avatar.user_id == user_id).order_by(Avatar.created_at.desc()))
    return list(res.scalars().all())


async def get(db: AsyncSession, avatar_id: str, user_id: str | None = None) -> Avatar | None:
    q = select(Avatar).where(Avatar.id == avatar_id)
    if user_id:
        q = q.where(Avatar.user_id == user_id)
    res = await db.execute(q)
    return res.scalar_one_or_none()


async def create(db: AsyncSession, **fields) -> Avatar:
    a = Avatar(**fields)
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


async def delete(db: AsyncSession, avatar: Avatar) -> None:
    await db.delete(avatar)
    await db.commit()
