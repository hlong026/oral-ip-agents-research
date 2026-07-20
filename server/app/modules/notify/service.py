"""notify 业务编排（F-734 部分：站内信 + 实时告警）"""
from datetime import UTC

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import CHANNEL_ALERT, publish

from . import repository as repo
from .models import Notification
from .schemas import NotificationOut, UnreadOut


async def notify_user(db: AsyncSession, user_id: str, level: str, title: str, body: str = "") -> None:
    """站内信落库 + 实时告警推送（供其他模块经 service 调用）"""
    await repo.create(db, user_id=user_id, level=level, title=title, body=body)
    await publish(CHANNEL_ALERT, {"level": level, "userId": user_id, "message": title, "body": body})


async def list_notifications(db: AsyncSession, user_id: str) -> list[NotificationOut]:
    return [to_out(n) for n in await repo.list_by_user(db, user_id)]


async def unread(db: AsyncSession, user_id: str) -> UnreadOut:
    return UnreadOut(count=await repo.unread_count(db, user_id))


async def mark_read(db: AsyncSession, user_id: str, notification_id: str) -> None:
    await repo.mark_read(db, user_id, notification_id)


async def mark_all_read(db: AsyncSession, user_id: str) -> None:
    await repo.mark_all_read(db, user_id)


def to_out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id, level=n.level, title=n.title, body=n.body, read=n.read,
        createdAt=n.created_at.astimezone(UTC).isoformat())
