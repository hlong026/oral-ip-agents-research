"""notify 路由（/notifications 站内信）"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user_id

from . import service
from .schemas import NotificationOut, UnreadOut

router = APIRouter(prefix="/notifications", tags=["notify"])


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> list[NotificationOut]:
    return await service.list_notifications(db, user_id)


@router.get("/unread-count", response_model=UnreadOut)
async def unread_count(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> UnreadOut:
    return await service.unread(db, user_id)


@router.post("/{notification_id}/read", status_code=204)
async def mark_read(
    notification_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.mark_read(db, user_id, notification_id)


@router.post("/read-all", status_code=204)
async def mark_all_read(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    await service.mark_all_read(db, user_id)
