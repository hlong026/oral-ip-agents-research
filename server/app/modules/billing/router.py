"""billing HTTP 层：额度查询 / 明细分页 / CSV 导出（F-602）"""

import csv
import io
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user_id, require_admin
from app.modules.auth.models import User as UserModel

from . import repository as repo
from .models import QuotaUsage
from .schemas import (
    AdminUsageItemOut,
    PricePreviewIn,
    QuotaOut,
    ReservationBatchOut,
    ReservationCreateIn,
    ReservationStateOut,
    UsagePageOut,
)
from .service import get_quota, release_reservation, reserve_quote, save_quote, usage_to_out

router = APIRouter(prefix="/billing", tags=["billing"])

# Admin 专用路由（管理员查看用户用量）
admin_router = APIRouter(prefix="/admin", tags=["admin-billing"])

_EXPORT_MAX_DAYS = 31
_EXPORT_MAX_ROWS = 50_000


def _export_window(created_from: datetime | None, created_to: datetime | None) -> tuple[datetime, datetime]:
    end = created_to or datetime.now(UTC)
    start = created_from or end - timedelta(days=_EXPORT_MAX_DAYS)
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    if end < start:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "EXPORT_RANGE_INVALID", "message": "导出结束时间不能早于开始时间"},
        )
    if end - start > timedelta(days=_EXPORT_MAX_DAYS):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "EXPORT_WINDOW_TOO_LARGE",
                "message": f"单次最多导出 {_EXPORT_MAX_DAYS} 天，请缩小时间范围",
            },
        )
    return start, end


async def _usage_csv_stream(db: AsyncSession, query) -> AsyncIterator[bytes]:
    yield "\ufeff时间,步骤,分辨率,点数,通道,trace_id\r\n".encode()
    rows = await db.stream_scalars(query.execution_options(yield_per=500))
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    async for usage in rows:
        writer.writerow(
            [
                usage.created_at.astimezone(UTC).isoformat(),
                usage.step,
                usage.resolution,
                usage.points,
                usage.compute,
                usage.trace_id,
            ]
        )
        if buffer.tell() >= 64 * 1024:
            yield buffer.getvalue().encode()
            buffer.seek(0)
            buffer.truncate(0)
    if buffer.tell():
        yield buffer.getvalue().encode()


async def _bounded_usage_export(db: AsyncSession, query, filename: str) -> StreamingResponse:
    total = int((await db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))) or 0)
    if total > _EXPORT_MAX_ROWS:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "code": "EXPORT_ROW_LIMIT_EXCEEDED",
                "message": f"单次最多导出 {_EXPORT_MAX_ROWS} 条，请缩小时间范围",
            },
        )
    return StreamingResponse(
        _usage_csv_stream(db, query),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/quota", response_model=QuotaOut)
async def api_quota(user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await get_quota(db, user_id)


@router.get("/balance", response_model=QuotaOut)
async def api_balance(user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await get_quota(db, user_id)


@router.post("/price-preview")
async def api_price_preview(
    body: PricePreviewIn,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    from app.modules.catalog.service import build_quote

    quote = await build_quote(db, [item.model_dump() for item in body.items])
    catalog_version_id = str(quote.pop("_catalogVersionId"))
    await save_quote(db, user_id, quote, catalog_version_id)
    quote["availablePoints"] = (await get_quota(db, user_id)).balance
    return quote


@router.post("/reservations", status_code=201, response_model=ReservationBatchOut)
async def api_reserve_quote(
    body: ReservationCreateIn,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await reserve_quote(db, user_id, body.quoteId, body.count)


@router.post("/reservations/{reservation_id}/release", response_model=ReservationStateOut)
async def api_release_reservation(
    reservation_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    from .models import CreditReservation

    reservation = await db.get(CreditReservation, reservation_id)
    if reservation is None or reservation.user_id != user_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "RESERVATION_NOT_FOUND", "message": "冻结记录不存在"},
        )
    if reservation.task_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "RESERVATION_BOUND", "message": "任务已接管该冻结，不能手动释放"},
        )
    released = await release_reservation(db, reservation_id, user_id)
    if released is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "RESERVATION_NOT_FOUND", "message": "冻结记录不存在"},
        )
    return released


@router.get("/usage")
async def api_usage(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    export: str | None = None,
    created_from: datetime | None = Query(None, alias="createdFrom"),
    created_to: datetime | None = Query(None, alias="createdTo"),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    if export == "csv":
        start, end = _export_window(created_from, created_to)
        query = (
            select(QuotaUsage)
            .where(
                QuotaUsage.user_id == user_id,
                QuotaUsage.created_at >= start,
                QuotaUsage.created_at <= end,
            )
            .order_by(QuotaUsage.created_at.desc())
        )
        return await _bounded_usage_export(db, query, "quota_usage.csv")
    items, total = await repo.list_usage(db, user_id, page, pageSize)
    return UsagePageOut(items=[usage_to_out(u) for u in items], total=total, page=page, pageSize=pageSize)


@admin_router.get("/usage")
async def admin_get_user_usage(
    user_id: str,
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    step: str | None = None,
    _admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """管理员查看指定用户的调用记录（需管理员权限）"""
    # 验证用户存在
    target_user = await db.get(UserModel, user_id)
    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"code": "USER_NOT_FOUND", "message": "用户不存在"}
        )

    # 构建查询
    query = select(QuotaUsage).where(QuotaUsage.user_id == user_id)

    # 可选过滤
    if step:
        query = query.where(QuotaUsage.step == step)

    # 总数
    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar() or 0

    # 分页
    offset = (page - 1) * pageSize
    res = await db.execute(query.order_by(QuotaUsage.created_at.desc()).offset(offset).limit(pageSize))
    items = list(res.scalars().all())

    # 序列化
    return {
        "items": [
            AdminUsageItemOut(
                id=u.id,
                step=u.step,
                resolution=u.resolution,
                points=u.points,
                compute=u.compute,
                createdAt=u.created_at.astimezone(UTC).isoformat(),
            ).model_dump()
            for u in items
        ],
        "total": total,
        "page": page,
        "pageSize": pageSize,
        "hasMore": (page * pageSize) < total,
    }


@admin_router.get("/usage/export")
async def admin_export_user_usage_csv(
    user_id: str,
    step: str | None = None,
    created_from: datetime | None = Query(None, alias="createdFrom"),
    created_to: datetime | None = Query(None, alias="createdTo"),
    _admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """导出单个用户的完整消费明细为 CSV（需管理员权限）"""
    # 验证用户存在
    target_user = await db.get(UserModel, user_id)
    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail={"code": "USER_NOT_FOUND", "message": "用户不存在"}
        )

    # 基础查询
    start, end = _export_window(created_from, created_to)
    query = select(QuotaUsage).where(
        QuotaUsage.user_id == user_id,
        QuotaUsage.created_at >= start,
        QuotaUsage.created_at <= end,
    )
    if step:
        query = query.where(QuotaUsage.step == step)
    return await _bounded_usage_export(
        db,
        query.order_by(QuotaUsage.created_at.desc()),
        f"usage_{user_id}.csv",
    )
