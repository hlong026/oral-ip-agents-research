"""dashboard 聚合（工作台数据卡 + 动态流）"""
from datetime import UTC

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user_id
from app.modules.billing.service import (
    get_quota,
    usage_to_out,  # noqa: F401  (契约复用)
)
from app.modules.pipeline.repository import list_by_user, stats

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class OverviewOut(BaseModel):
    todayDone: int
    todayDelta: int
    queued: int
    published: int
    weekDelta: int
    pendingAlerts: int
    quotaBalance: float
    quotaUsed: float


class FeedEvent(BaseModel):
    id: str
    type: str  # ok | err | info | run
    text: str
    createdAt: str


_STATUS_FEED = {
    "done": ("ok", "全流程完成"),
    "failed": ("err", "执行失败"),
    "running": ("run", "执行中"),
    "waiting_confirm": ("info", "等待人工确认"),
    "pending": ("info", "已排队"),
    "canceled": ("info", "已取消"),
}


@router.get("/overview", response_model=OverviewOut)
async def overview(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> OverviewOut:
    s = await stats(db, user_id)
    q = await get_quota(db, user_id)
    return OverviewOut(**s, quotaBalance=q.balance, quotaUsed=q.usedThisMonth)


@router.get("/feed", response_model=list[FeedEvent])
async def feed(
    limit: int = Query(20, ge=1, le=50),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> list[FeedEvent]:
    """动态流：由最近任务状态聚合（实时事件经 WS CHANNEL_FEED 推送）"""
    items, _ = await list_by_user(db, user_id, None, 1, limit)
    out: list[FeedEvent] = []
    for t in items:
        type_, label = _STATUS_FEED.get(t.status, ("info", t.status))
        step = f" · {t.current_step}" if t.status == "running" and t.current_step else ""
        out.append(FeedEvent(
            id=t.id[:12], type=type_, text=f"「{t.title[:18]}」{label}{step}",
            createdAt=t.updated_at.astimezone(UTC).isoformat()))
    return out
