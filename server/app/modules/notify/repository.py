"""notify 数据访问"""
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Notification


async def create(db: AsyncSession, **fields) -> Notification:
    n = Notification(**fields)
    db.add(n)
    await db.commit()
    await db.refresh(n)
    return n


async def list_by_user(db: AsyncSession, user_id: str, limit: int = 30) -> list[Notification]:
    res = await db.execute(
        select(Notification).where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc()).limit(limit))
    return list(res.scalars().all())


async def unread_count(db: AsyncSession, user_id: str) -> int:
    return int((await db.execute(
        select(func.count(Notification.id))
        .where(Notification.user_id == user_id, Notification.read.is_(False)))).scalar() or 0)


async def mark_read(db: AsyncSession, user_id: str, notification_id: str) -> None:
    await db.execute(
        update(Notification)
        .where(Notification.id == notification_id, Notification.user_id == user_id)
        .values(read=True))
    await db.commit()


async def mark_all_read(db: AsyncSession, user_id: str) -> None:
    await db.execute(
        update(Notification).where(Notification.user_id == user_id).values(read=True))
    await db.commit()
