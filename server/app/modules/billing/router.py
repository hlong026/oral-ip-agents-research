"""billing HTTP 层：额度查询 / 明细分页 / 消费流水 / CSV 导出（F-602）"""

import csv
import io
import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user_id

from . import repository as repo
from .schemas import (
    LedgerItemOut,
    LedgerPageOut,
    PricePreviewIn,
    QuotaOut,
    ReservationBatchOut,
    ReservationCreateIn,
    ReservationStateOut,
    UsagePageOut,
)
from .service import (
    all_ledger_for_export,
    get_quota,
    list_ledger,
    release_reservation,
    reserve_quote,
    save_quote,
    usage_to_out,
)

router = APIRouter(prefix="/billing", tags=["billing"])


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
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    if export == "csv":
        rows = await repo.all_usage(db, user_id)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["时间", "步骤", "分辨率", "点数", "通道", "trace_id"])
        for u in rows:
            writer.writerow([u.created_at.isoformat(), u.step, u.resolution, u.points, u.compute, u.trace_id])
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue().encode("utf-8-sig")]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=quota_usage.csv"},
        )
    items, total = await repo.list_usage(db, user_id, page, pageSize)
    return UsagePageOut(items=[usage_to_out(u) for u in items], total=total, page=page, pageSize=pageSize)


@router.get("/ledger", response_model=LedgerPageOut)
async def api_ledger(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    eventType: str | None = Query(None, description="事件类型: grant/reserve/settle/release/expire/adjustment"),
    startDate: str | None = Query(None, description="开始日期 ISO 格式"),
    endDate: str | None = Query(None, description="结束日期 ISO 格式"),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """用户端消费明细：按日/周/月查看积分流水。"""
    start_date = _parse_date(startDate) if startDate else None
    end_date = _parse_date(endDate, end_of_day=True) if endDate else None
    items, total = await list_ledger(
        db,
        user_id,
        page=page,
        page_size=pageSize,
        event_type=eventType,
        start_date=start_date,
        end_date=end_date,
    )
    return LedgerPageOut(
        items=[_ledger_to_out(item) for item in items],
        total=total,
        page=page,
        pageSize=pageSize,
    )


@router.get("/ledger/export")
async def api_ledger_export(
    startDate: str | None = Query(None),
    endDate: str | None = Query(None),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """导出消费明细 CSV。"""
    start_date = _parse_date(startDate) if startDate else None
    end_date = _parse_date(endDate, end_of_day=True) if endDate else None
    rows = await all_ledger_for_export(db, user_id, start_date=start_date, end_date=end_date)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["时间", "事件类型", "积分变动", "引用类型", "引用ID", "任务ID", "操作人", "详情"])
    for item in rows:
        writer.writerow(
            [
                item.created_at.isoformat(),
                item.event_type,
                item.points_delta,
                item.reference_type,
                item.reference_id,
                item.task_id,
                item.created_by,
                item.detail_json or "",
            ]
        )
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=credit_ledger.csv"},
    )


def _parse_date(value: str, *, end_of_day: bool = False) -> datetime:
    """解析日期字符串，支持 YYYY-MM-DD 或 ISO 格式。"""
    try:
        if len(value) == 10:
            dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
            if end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59)
            return dt
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        else:
            dt = dt.astimezone(UTC)
        return dt
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_DATE", "message": f"无法解析日期: {value}"},
        ) from exc


def _ledger_to_out(item) -> LedgerItemOut:
    detail = None
    try:
        detail = json.loads(item.detail_json) if item.detail_json and item.detail_json != "{}" else None
    except (json.JSONDecodeError, TypeError):
        pass
    return LedgerItemOut(
        id=item.id,
        eventType=item.event_type,
        pointsDelta=item.points_delta,
        referenceType=item.reference_type,
        referenceId=item.reference_id,
        taskId=item.task_id,
        detail=detail,
        createdBy=item.created_by,
        createdAt=item.created_at.astimezone(UTC).isoformat(),
    )
