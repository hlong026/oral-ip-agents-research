"""管理员用户、成本和审计查询。"""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditLog, write_audit
from app.core.db import get_db
from app.core.deps import require_admin
from app.modules.auth.models import User
from app.modules.billing.models import QuotaAccount
from app.modules.catalog import repository as catalog_repo

router = APIRouter(tags=["admin"])


class UserUpdateIn(BaseModel):
    role: Literal["user", "admin"] | None = None
    isActive: bool | None = None


class CreditAdjustIn(BaseModel):
    points: int = Field(ge=-10_000_000, le=10_000_000)
    reason: str = Field(min_length=3, max_length=500)
    expiresAt: datetime | None = None

    @field_validator("points")
    @classmethod
    def points_must_not_be_zero(cls, value: int) -> int:
        if value == 0:
            raise ValueError("调整积分不能为 0")
        return value


@router.get("/users")
async def list_users(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    _admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    total = int((await db.execute(select(func.count(User.id)))).scalar() or 0)
    rows = await db.execute(
        select(User, QuotaAccount.balance)
        .outerjoin(QuotaAccount, QuotaAccount.user_id == User.id)
        .order_by(User.created_at.desc())
        .offset((page - 1) * pageSize)
        .limit(pageSize)
    )
    return {
        "items": [
            {
                "id": user.id,
                "phone": user.phone,
                "nickname": user.nickname,
                "role": user.role,
                "isActive": user.is_active,
                "planType": user.plan_type,
                "planSkuCode": user.plan_sku_code,
                "planExpiresAt": user.plan_expires_at.isoformat() if user.plan_expires_at else None,
                "balance": balance or 0,
                "createdAt": user.created_at.astimezone(UTC).isoformat(),
            }
            for user, balance in rows.all()
        ],
        "total": total,
        "page": page,
        "pageSize": pageSize,
    }


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    body: UserUpdateIn,
    admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "USER_NOT_FOUND", "message": "用户不存在"})
    if user_id == admin_id and (body.role == "user" or body.isActive is False):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "SELF_LOCKOUT", "message": "不能停用或降级当前管理员"},
        )
    if body.role is not None:
        user.role = body.role
    if body.isActive is not None:
        user.is_active = body.isActive
    await db.commit()
    await write_audit(
        "admin_user_updated",
        user_id=admin_id,
        detail=f"target={user_id},role={body.role},active={body.isActive}",
    )
    return {"id": user.id, "role": user.role, "isActive": user.is_active}


@router.post("/users/{user_id}/credits/adjust")
async def adjust_user_credits(
    user_id: str,
    body: CreditAdjustIn,
    admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if await db.get(User, user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "USER_NOT_FOUND", "message": "用户不存在"})
    from app.modules.billing.service import adjust_points

    balance = await adjust_points(
        db,
        user_id,
        body.points,
        body.reason,
        admin_id,
        body.expiresAt,
    )
    await write_audit(
        "admin_credit_adjusted",
        user_id=admin_id,
        detail=f"target={user_id},points={body.points},reason={body.reason[:200]}",
    )
    return balance


@router.get("/cost-analysis")
async def cost_analysis(
    _admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    version = await catalog_repo.active_price_version(db)
    if version is None:
        return {"priceVersion": None, "items": []}
    prices = await catalog_repo.all_module_prices(db, version.id)
    return {
        "priceVersion": version.version,
        "items": [
            {
                "module": item.module,
                "displayName": item.display_name,
                "pointsPerUnit": item.points_per_unit,
                "internalCostCentsPerUnit": item.internal_cost_cents_per_unit,
                "targetMarginBps": item.target_margin_bps,
                "enabled": item.enabled,
            }
            for item in prices
        ],
    }


@router.get("/audit")
async def list_audit(
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=200),
    _admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    total = int((await db.execute(select(func.count(AuditLog.id)))).scalar() or 0)
    rows = await db.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).offset((page - 1) * pageSize).limit(pageSize)
    )
    return {
        "items": [
            {
                "id": item.id,
                "event": item.event,
                "userId": item.user_id,
                "traceId": item.trace_id,
                "taskId": item.task_id,
                "detail": item.detail,
                "createdAt": item.created_at.astimezone(UTC).isoformat(),
            }
            for item in rows.scalars().all()
        ],
        "total": total,
        "page": page,
        "pageSize": pageSize,
    }
