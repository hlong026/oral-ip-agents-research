"""管理员用户、成本和审计查询。"""

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditLog, write_audit
from app.core.db import get_db
from app.core.deps import require_admin
from app.modules.admin.dashboard import build_dashboard
from app.modules.auth.models import RefreshSession, User
from app.modules.billing.models import QuotaAccount
from app.modules.catalog import repository as catalog_repo

router = APIRouter(tags=["admin"])


@router.get("/dashboard")
async def dashboard(
    days: int = Query(30, ge=7, le=90),
    _admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """运营总览驾驶舱：六大业务块按天时间序列，一次请求全量返回"""
    return await build_dashboard(db, days)


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


class ReconciliationIn(BaseModel):
    action: Literal["release", "settle", "resume"]
    reason: str = Field(min_length=3, max_length=500)
    providerTaskId: str | None = Field(default=None, max_length=128)


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
    users = rows.all()
    # 反查绑定激活码（渠道 + 摘要掩码，明文不可回显），供运营识别激活码用户
    from app.modules.activation.models import ActivationCode

    user_ids = [user.id for user, _ in users]
    code_masked: dict[str, str] = {}
    if user_ids:
        codes = (await db.execute(select(ActivationCode).where(ActivationCode.bound_user_id.in_(user_ids)))).scalars()
        for code in codes:
            masked = f"{code.code[:4].upper()}****{code.code[-4:].upper()}"
            if code.channel:
                masked = f"{code.channel}·{masked}"
            code_masked.setdefault(code.bound_user_id or "", masked)
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
                "deviceBound": bool(user.device_fingerprint),
                "activationCodeMasked": code_masked.get(user.id),
                "balance": balance or 0,
                "createdAt": user.created_at.astimezone(UTC).isoformat(),
            }
            for user, balance in users
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


@router.post("/users/{user_id}/unbind-device")
async def unbind_device(
    user_id: str,
    admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """清空设备绑定并吊销全部刷新会话，用户可在新设备重新登录绑定"""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "USER_NOT_FOUND", "message": "用户不存在"})
    user.device_fingerprint = ""
    sessions = await db.execute(
        select(RefreshSession).where(RefreshSession.user_id == user_id, RefreshSession.revoked.is_(False))
    )
    for session in sessions.scalars().all():
        session.revoked = True
    await db.commit()
    await write_audit("admin_device_unbound", user_id=admin_id, detail=f"target={user_id}")
    return {"ok": True}


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


@router.get("/reconciliations")
async def list_reconciliations(
    _admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """列出外部非幂等提交结果未知、仍保留积分冻结的记录。"""
    from app.modules.avatar.models import Avatar
    from app.modules.pipeline.models import PipelineTask
    from app.modules.voice.models import Voice

    pipeline_tasks = (
        await db.execute(
            select(PipelineTask)
            .where(PipelineTask.status == "reconciliation_required")
            .order_by(PipelineTask.updated_at.asc())
        )
    ).scalars()
    voices = (
        await db.execute(
            select(Voice).where(Voice.status == "reconciliation_required").order_by(Voice.created_at.asc())
        )
    ).scalars()
    avatars = (
        await db.execute(
            select(Avatar).where(Avatar.status == "reconciliation_required").order_by(Avatar.created_at.asc())
        )
    ).scalars()
    items = [
        {
            "kind": "pipeline",
            "id": item.id,
            "userId": item.user_id,
            "name": item.title,
            "step": item.current_step,
            "reservationId": item.reservation_id,
            "createdAt": item.created_at.astimezone(UTC).isoformat(),
        }
        for item in pipeline_tasks
    ]
    items += [
        {
            "kind": "voice",
            "id": item.id,
            "userId": item.user_id,
            "name": item.name,
            "step": "voice_clone",
            "reservationId": item.reservation_id,
            "createdAt": item.created_at.astimezone(UTC).isoformat(),
        }
        for item in voices
    ]
    items += [
        {
            "kind": "avatar",
            "id": item.id,
            "userId": item.user_id,
            "name": item.name,
            "step": "avatar_clone",
            "reservationId": item.reservation_id,
            "createdAt": item.created_at.astimezone(UTC).isoformat(),
        }
        for item in avatars
    ]
    return {"items": sorted(items, key=lambda item: item["createdAt"]), "total": len(items)}


@router.post("/reconciliations/{kind}/{record_id}")
async def resolve_reconciliation(
    kind: Literal["pipeline", "voice", "avatar"],
    record_id: str,
    body: ReconciliationIn,
    admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """管理员根据供应商后台证据恢复轮询，或结算/释放冻结后关闭未知状态。"""
    from app.modules.avatar.models import Avatar
    from app.modules.billing.service import release_reservation, settle_reservation
    from app.modules.pipeline.models import PipelineTask
    from app.modules.voice.models import Voice

    model = {"pipeline": PipelineTask, "voice": Voice, "avatar": Avatar}[kind]
    record: Any = await db.get(model, record_id)
    if record is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "RECONCILIATION_NOT_FOUND", "message": "待对账记录不存在"},
        )
    if record.status != "reconciliation_required":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "RECONCILIATION_CLOSED", "message": "该记录已完成对账"},
        )

    reservation_id = str(record.reservation_id or "")
    if body.action == "resume":
        if kind == "pipeline" or not body.providerTaskId:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "PROVIDER_TASK_ID_REQUIRED",
                    "message": "声音或数字人恢复轮询必须填写供应商任务 ID",
                },
            )
        record.provider_task_id = body.providerTaskId
        record.provider = "hifly-voice" if kind == "voice" else "hifly-avatar"
        record.status = "training"
        result_status = "training"
    elif body.action == "settle":
        if (
            not reservation_id
            or await settle_reservation(
                db,
                reservation_id,
                record.id,
                step="pipeline" if kind == "pipeline" else f"{kind}_clone",
            )
            <= 0
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "RESERVATION_UNAVAILABLE", "message": "积分冻结不可结算"},
            )
        record.status = "failed"
        result_status = "settled"
    else:
        released = await release_reservation(db, reservation_id, record.user_id) if reservation_id else None
        if released is None or released.status != "released":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "RESERVATION_UNAVAILABLE", "message": "积分冻结不可释放"},
            )
        record.status = "failed"
        result_status = "released"

    if kind == "pipeline" and body.action != "resume":
        record.error = f"人工对账已完成：{body.reason}"
    await db.commit()
    await write_audit(
        "provider_reconciliation_resolved",
        user_id=admin_id,
        task_id=record.id,
        detail=f"kind={kind},action={body.action},reason={body.reason[:300]}",
    )
    return {"kind": kind, "id": record.id, "status": record.status, "reservationStatus": result_status}
