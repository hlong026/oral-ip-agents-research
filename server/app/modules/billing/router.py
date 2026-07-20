"""billing HTTP 层：额度查询 / 明细分页 / CSV 导出（F-602）"""
import csv
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user_id

from . import repository as repo
from .schemas import QuotaOut, UsagePageOut
from .service import get_quota, usage_to_out

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/quota", response_model=QuotaOut)
async def api_quota(user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await get_quota(db, user_id)


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
