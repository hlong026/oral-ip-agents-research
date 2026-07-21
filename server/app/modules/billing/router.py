"""billing HTTP 层：额度查询 / 明细分页 / CSV 导出（F-602）"""

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user_id

from . import repository as repo
from .schemas import (
    PricePreviewIn,
    QuotaOut,
    ReservationBatchOut,
    ReservationCreateIn,
    ReservationStateOut,
    UsagePageOut,
)
from .service import get_quota, release_reservation, reserve_quote, save_quote, usage_to_out

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
