"""activation HTTP 路由（用户侧 + 管理侧）"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user_id, require_permission

from . import repository as repo
from . import service
from .schemas import (
    ActivateIn,
    ActivateOut,
    BatchCreateIn,
    BatchGenerateOut,
    BatchOut,
    CodeInfoOut,
    CodeOut,
    CodeStatsOut,
    RedeemIn,
    RedeemOut,
    SubscriptionOut,
    ValidateCodeIn,
)

router = APIRouter(prefix="/activation", tags=["activation"])
subscription_router = APIRouter(tags=["subscription"])
admin_router = APIRouter(prefix="/activation", tags=["admin-activation"])


# ---------- 用户侧 ----------


@router.post("/validate-code", response_model=CodeInfoOut)
async def api_validate_code(body: ValidateCodeIn, request: Request, db: AsyncSession = Depends(get_db)):
    """预校验激活码有效性（无需登录）"""
    from .rate_limit import enforce_rate_limit, record_attempt

    ip_address = request.client.host if request.client else "unknown"
    device = body.deviceFingerprint or request.headers.get("X-Device-Fingerprint", "")
    await enforce_rate_limit("validate", ip_address=ip_address, device_fingerprint=device)
    result = await service.validate_code(db, body.code)
    await record_attempt(
        "validate",
        success=result.valid,
        ip_address=ip_address,
        device_fingerprint=device,
    )
    return result


@router.post("/activate", response_model=ActivateOut)
async def api_activate(body: ActivateIn, request: Request, db: AsyncSession = Depends(get_db)):
    """激活码注册（首次开户，无需登录）"""
    from .rate_limit import enforce_rate_limit, record_attempt

    ip_address = request.client.host if request.client else "unknown"
    await enforce_rate_limit(
        "activate",
        ip_address=ip_address,
        device_fingerprint=body.deviceFingerprint,
        phone=body.phone,
    )
    try:
        result = await service.activate(db, body.code, body.phone, body.password, body.nickname, body.deviceFingerprint)
    except HTTPException:
        await db.rollback()
        await record_attempt(
            "activate",
            success=False,
            ip_address=ip_address,
            device_fingerprint=body.deviceFingerprint,
            phone=body.phone,
        )
        raise
    await record_attempt(
        "activate",
        success=True,
        ip_address=ip_address,
        device_fingerprint=body.deviceFingerprint,
        phone=body.phone,
    )
    return result


@router.post("/redeem", response_model=RedeemOut)
async def api_redeem(
    body: RedeemIn,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """已登录用户兑换新码（续费/充值）"""
    return await service.redeem(db, user_id, body.code)


@router.get("/subscription", response_model=SubscriptionOut)
async def api_subscription(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """查询当前订阅状态（自动检查到期）"""
    return await service.get_subscription_with_expiry_check(db, user_id)


@subscription_router.get("/subscription", response_model=SubscriptionOut)
async def api_current_subscription(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await service.get_subscription_with_expiry_check(db, user_id)


# ---------- 管理侧 ----------


@admin_router.post("/batches", status_code=201, response_model=BatchGenerateOut)
async def api_admin_generate_batch(
    body: BatchCreateIn,
    admin_id: str = Depends(require_permission("activation.manage")),
    db: AsyncSession = Depends(get_db),
):
    return await service.generate_batch(
        db,
        body.name,
        body.planType,
        body.quotaAmount,
        body.durationDays,
        body.count,
        body.channel,
        body.codeExpiresAt,
        created_by=admin_id,
        sku_version_id=body.skuVersionId,
    )


@admin_router.get("/codes")
async def api_list_codes(
    status: str | None = Query(None),
    batchId: str | None = Query(None),
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=200),
    _user_id: str = Depends(require_permission("activation.read")),
    db: AsyncSession = Depends(get_db),
):
    """码列表（分页/筛选）"""
    codes, total = await repo.list_codes(db, status=status, batch_id=batchId, page=page, page_size=pageSize)
    return {
        "items": [_code_to_out(c) for c in codes],
        "total": total,
        "page": page,
        "pageSize": pageSize,
    }


@admin_router.get("/batches")
async def api_list_batches(
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=200),
    _user_id: str = Depends(require_permission("activation.read")),
    db: AsyncSession = Depends(get_db),
):
    """批次列表"""
    batches, total = await repo.list_batches(db, page=page, page_size=pageSize)
    return {
        "items": [_batch_to_out(b) for b in batches],
        "total": total,
        "page": page,
        "pageSize": pageSize,
    }


@admin_router.put("/codes/{code_id}/revoke")
async def api_revoke_code(
    code_id: str,
    admin_id: str = Depends(require_permission("activation.manage")),
    db: AsyncSession = Depends(get_db),
):
    """作废单个码"""
    await service.revoke_code_by_id(db, code_id, admin_id)
    return {"ok": True}


@admin_router.put("/batches/{batch_id}/revoke")
async def api_revoke_batch(
    batch_id: str,
    admin_id: str = Depends(require_permission("activation.manage")),
    db: AsyncSession = Depends(get_db),
):
    """批量作废"""
    count = await service.revoke_batch_codes(db, batch_id, admin_id)
    return {"ok": True, "revoked": count}


@admin_router.get("/stats", response_model=CodeStatsOut)
async def api_stats(
    _user_id: str = Depends(require_permission("activation.read")),
    db: AsyncSession = Depends(get_db),
):
    """码统计"""
    return await service.get_stats(db)


# ---------- 序列化辅助 ----------


def _code_to_out(c) -> CodeOut:
    from datetime import UTC

    return CodeOut(
        id=c.id,
        code="configured",
        planType=c.plan_type,
        quotaAmount=c.quota_amount,
        durationDays=c.duration_days,
        status=c.status,
        channel=c.channel,
        boundUserId=c.bound_user_id,
        activatedAt=c.activated_at.astimezone(UTC).isoformat() if c.activated_at else None,
        expiresAt=c.expires_at.astimezone(UTC).isoformat() if c.expires_at else None,
        createdAt=c.created_at.astimezone(UTC).isoformat(),
    )


def _batch_to_out(b) -> BatchOut:
    from datetime import UTC

    return BatchOut(
        id=b.id,
        name=b.name,
        planType=b.plan_type,
        quotaAmount=b.quota_amount,
        durationDays=b.duration_days,
        totalCount=b.total_count,
        usedCount=b.used_count,
        channel=b.channel,
        createdAt=b.created_at.astimezone(UTC).isoformat(),
    )
