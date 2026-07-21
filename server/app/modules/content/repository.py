"""content 数据访问"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Script


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
