"""管理员用户、成本和审计查询（RBAC 权限点 + 资金类二次确认 + 同事务审计）。"""

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditLog, add_audit
from app.core.db import get_db
from app.core.deps import ADMIN_ROLES, require_permission
from app.modules.auth.models import User
from app.modules.billing.models import QuotaAccount
from app.modules.catalog import repository as catalog_repo

router = APIRouter(tags=["admin"])

# 资金类操作二次确认阈值：扣减（负数）或单次 |points| 达到该值必须 confirm=true。
# 设计认知：该控制是防手滑的 UI 摩擦，不防分次拆分绕过（如多次 9,999）；滥用防护依赖审计追溯。
CREDIT_CONFIRM_THRESHOLD = 10_000


class UserUpdateIn(BaseModel):
    role: Literal["user", "admin", "ops", "finance", "auditor"] | None = None
    isActive: bool | None = None


class CreditAdjustIn(BaseModel):
    points: int = Field(ge=-10_000_000, le=10_000_000)
    reason: str = Field(min_length=3, max_length=500)
    expiresAt: datetime | None = None
    confirm: bool = False  # 大额/扣减调整必须显式置 true（二次确认）

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
    _admin_id: str = Depends(require_permission("users.read")),
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
    admin_id: str = Depends(require_permission("users.write")),
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
    # 角色变更或停用/启用「管理账号」均属于提权操作，仅超管可执行
    # （M2 修复：ops 拥有 users.write 但不得停用其他管理账号，防止管理面自锁）
    needs_super_admin = body.role is not None or (body.isActive is not None and user.role in ADMIN_ROLES)
    if needs_super_admin:
        operator = await db.get(User, admin_id)
        if operator is None or operator.role != "admin":
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail={"code": "FORBIDDEN", "message": "仅超级管理员可变更管理账号角色或状态"},
            )
    if body.role is not None:
        user.role = body.role
    if body.isActive is not None:
        user.is_active = body.isActive
    # 权限类 A 级事件：审计与业务同事务提交
    add_audit(
        db,
        "admin_user_updated",
        user_id=admin_id,
        detail=f"target={user_id},role={body.role},active={body.isActive}",
    )
    await db.commit()
    return {"id": user.id, "role": user.role, "isActive": user.is_active}


@router.post("/users/{user_id}/credits/adjust")
async def adjust_user_credits(
    user_id: str,
    body: CreditAdjustIn,
    admin_id: str = Depends(require_permission("billing.adjust")),
    db: AsyncSession = Depends(get_db),
):
    if await db.get(User, user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "USER_NOT_FOUND", "message": "用户不存在"})
    # 资金类二次确认：扣减或大额调整必须显式 confirm
    if (body.points < 0 or abs(body.points) >= CREDIT_CONFIRM_THRESHOLD) and not body.confirm:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "CONFIRM_REQUIRED",
                "message": "扣减或大额积分调整需二次确认，请置 confirm=true 后重试",
            },
        )
    from app.modules.billing.service import adjust_points

    # 资金类 A 级事件：审计先入业务 Session，随 adjust_points 的事务一并提交/回滚
    add_audit(
        db,
        "admin_credit_adjusted",
        user_id=admin_id,
        detail=f"target={user_id},points={body.points},reason={body.reason[:200]}",
    )
    balance = await adjust_points(
        db,
        user_id,
        body.points,
        body.reason,
        admin_id,
        body.expiresAt,
    )
    return balance


@router.get("/cost-analysis")
async def cost_analysis(
    _admin_id: str = Depends(require_permission("cost.read")),
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


@router.get("/overview")
async def admin_overview(
    _admin_id: str = Depends(require_permission("users.read")),
    db: AsyncSession = Depends(get_db),
):
    """运营总览聚合指标（只读，ops/finance/auditor/admin 均可访问）"""
    from app.modules.activation.models import ActivationCode
    from app.modules.billing.models import CreditLedger
    from app.modules.pipeline.models import PipelineTask

    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    expiry_horizon = now + timedelta(days=7)

    async def _count(stmt) -> int:
        return int((await db.execute(stmt)).scalar() or 0)

    total_users = await _count(select(func.count(User.id)))
    new_users_today = await _count(select(func.count(User.id)).where(User.created_at >= today_start))

    total_tasks = await _count(select(func.count(PipelineTask.id)))
    done_tasks_today = await _count(
        select(func.count(PipelineTask.id)).where(
            PipelineTask.status == "done",
            PipelineTask.updated_at >= today_start,
        )
    )

    total_codes = await _count(select(func.count(ActivationCode.id)))
    used_codes = await _count(select(func.count(ActivationCode.id)).where(ActivationCode.status == "used"))

    total_granted = float((await db.execute(select(func.coalesce(func.sum(QuotaAccount.total_granted), 0)))).scalar() or 0)
    # 实际消耗 = 冻结（reserve 负值）净扣除解冻退回（release 正值）；
    # settle 流水的 points_delta 恒为 0，不能直接用于统计
    total_consumed = abs(
        float(
            (
                await db.execute(
                    select(func.coalesce(func.sum(CreditLedger.points_delta), 0)).where(
                        CreditLedger.event_type.in_(["reserve", "release"])
                    )
                )
            ).scalar()
            or 0
        )
    )

    expiring_subscriptions = await _count(
        select(func.count(User.id)).where(
            User.plan_type != "none",
            User.plan_expires_at.is_not(None),
            User.plan_expires_at >= now,
            User.plan_expires_at <= expiry_horizon,
        )
    )

    return {
        "totalUsers": total_users,
        "newUsersToday": new_users_today,
        "totalTasks": total_tasks,
        "doneTasksToday": done_tasks_today,
        "totalCodes": total_codes,
        "usedCodes": used_codes,
        "totalGranted": total_granted,
        "totalConsumed": total_consumed,
        "expiringSubscriptions": expiring_subscriptions,
    }


@router.get("/audit")
async def list_audit(
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=200),
    _admin_id: str = Depends(require_permission("audit.read")),
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
