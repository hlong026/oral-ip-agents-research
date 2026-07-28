"""管理员用户、成本、审计与设备绑定治理。"""

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditLog, write_audit
from app.core.db import get_db
from app.core.deps import require_admin
from app.modules.admin.dashboard import build_dashboard
from app.modules.auth.devices import get_device_bind_limit, list_user_devices
from app.modules.auth.models import DeviceBindRequest, RefreshSession, User, UserDevice, device_key_of
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
    device_counts: dict[str, int] = {}
    if user_ids:
        codes = (await db.execute(select(ActivationCode).where(ActivationCode.bound_user_id.in_(user_ids)))).scalars()
        for code in codes:
            masked = f"{code.code[:4].upper()}****{code.code[-4:].upper()}"
            if code.channel:
                masked = f"{code.channel}·{masked}"
            code_masked.setdefault(code.bound_user_id or "", masked)
        counts = await db.execute(
            select(UserDevice.user_id, func.count(UserDevice.id))
            .where(UserDevice.user_id.in_(user_ids))
            .group_by(UserDevice.user_id)
        )
        device_counts = {user_id: int(count) for user_id, count in counts.all()}
    device_limit = await get_device_bind_limit()
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
                "deviceBound": device_counts.get(user.id, 0) > 0,
                "deviceCount": device_counts.get(user.id, 0),
                "deviceLimit": device_limit,
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
    """解绑全部设备并吊销全部刷新会话，用户可在任意设备重新登录首绑"""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "USER_NOT_FOUND", "message": "用户不存在"})
    user.device_fingerprint = ""  # 废弃字段同步清空，避免残留脏数据
    await db.execute(sa_delete(UserDevice).where(UserDevice.user_id == user_id))
    sessions = await db.execute(
        select(RefreshSession).where(RefreshSession.user_id == user_id, RefreshSession.revoked.is_(False))
    )
    for session in sessions.scalars().all():
        session.revoked = True
    await db.commit()
    await write_audit("admin_device_unbound", user_id=admin_id, detail=f"target={user_id},scope=all")
    return {"ok": True}


def _device_out(device: UserDevice) -> dict[str, Any]:
    return {
        "id": device.id,
        "deviceKey": device.device_key,
        "deviceName": device.device_name,
        "source": device.source,
        "createdAt": device.created_at.astimezone(UTC).isoformat(),
        "lastSeenAt": device.last_seen_at.astimezone(UTC).isoformat(),
    }


async def _unbind_single_device(db: AsyncSession, device: UserDevice) -> None:
    """删设备行 + 吊销该设备指纹对应的刷新会话（不 commit，由调用方控制事务）"""
    sessions = await db.execute(
        select(RefreshSession).where(
            RefreshSession.user_id == device.user_id,
            RefreshSession.revoked.is_(False),
        )
    )
    # 设备段等值比较（LIKE 前缀匹配存在通配符/空 key 过量吊销风险）
    for session in sessions.scalars().all():
        if device_key_of(session.device_id) == device.device_key:
            session.revoked = True
    await db.delete(device)


@router.get("/users/{user_id}/devices")
async def list_devices(
    user_id: str,
    _admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """用户已绑定设备列表"""
    if await db.get(User, user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "USER_NOT_FOUND", "message": "用户不存在"})
    devices = await list_user_devices(db, user_id)
    return {"items": [_device_out(d) for d in devices], "limit": await get_device_bind_limit()}


@router.post("/users/{user_id}/devices/{device_id}/unbind")
async def unbind_single_device(
    user_id: str,
    device_id: str,
    admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """单设备解绑（删行 + 吊销对应会话，该设备 refresh 立即失效）"""
    device = await db.get(UserDevice, device_id)
    if device is None or device.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "DEVICE_NOT_FOUND", "message": "设备不存在"})
    device_key = device.device_key
    await _unbind_single_device(db, device)
    await db.commit()
    await write_audit("admin_device_unbound", user_id=admin_id, detail=f"target={user_id},device={device_key[:8]}")
    return {"ok": True}


class DeviceRequestApproveIn(BaseModel):
    unbindDeviceId: str | None = None


@router.get("/device-requests")
async def list_device_requests(
    status_filter: str = Query("pending", alias="status", pattern="^(pending|approved|rejected|all)$"),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    _admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """设备绑定申请列表（关联用户掩码激活码与当前设备列表，供审批选择解绑目标）"""
    from app.modules.activation.models import ActivationCode

    conditions = [] if status_filter == "all" else [DeviceBindRequest.status == status_filter]
    total = int((await db.execute(select(func.count(DeviceBindRequest.id)).where(*conditions))).scalar() or 0)
    rows = (
        (
            await db.execute(
                select(DeviceBindRequest)
                .where(*conditions)
                .order_by(DeviceBindRequest.created_at.desc())
                .offset((page - 1) * pageSize)
                .limit(pageSize)
            )
        )
        .scalars()
        .all()
    )
    user_ids = list({r.user_id for r in rows})
    users_map: dict[str, User] = {}
    code_masked: dict[str, str] = {}
    devices_map: dict[str, list[UserDevice]] = {}
    if user_ids:
        for user in (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars():
            users_map[user.id] = user
        codes = (await db.execute(select(ActivationCode).where(ActivationCode.bound_user_id.in_(user_ids)))).scalars()
        for code in codes:
            code_masked.setdefault(code.bound_user_id or "", f"{code.code[:4].upper()}****{code.code[-4:].upper()}")
        for device in (await db.execute(select(UserDevice).where(UserDevice.user_id.in_(user_ids)))).scalars():
            devices_map.setdefault(device.user_id, []).append(device)
    return {
        "items": [
            {
                "id": item.id,
                "userId": item.user_id,
                "nickname": users_map[item.user_id].nickname if item.user_id in users_map else "",
                "activationCodeMasked": code_masked.get(item.user_id),
                "deviceKey": item.device_key,
                "deviceName": item.device_name,
                "status": item.status,
                "createdAt": item.created_at.astimezone(UTC).isoformat(),
                "resolvedAt": item.resolved_at.astimezone(UTC).isoformat() if item.resolved_at else None,
                "boundDevices": [_device_out(d) for d in devices_map.get(item.user_id, [])],
            }
            for item in rows
        ],
        "total": total,
        "page": page,
        "pageSize": pageSize,
        "limit": await get_device_bind_limit(),
    }


@router.post("/device-requests/{request_id}/approve")
async def approve_device_request(
    request_id: str,
    body: DeviceRequestApproveIn,
    admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """批准申请：解绑指定旧设备腾出名额，新设备下次登录自动绑定。
    若当前设备数已 < 上限（如管理员已手动解绑），unbindDeviceId 可空直接批准。"""
    req = await db.get(DeviceBindRequest, request_id)
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "REQUEST_NOT_FOUND", "message": "申请不存在"})
    if req.status != "pending":
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail={"code": "REQUEST_RESOLVED", "message": "该申请已处理"}
        )
    if body.unbindDeviceId:
        device = await db.get(UserDevice, body.unbindDeviceId)
        if device is None or device.user_id != req.user_id:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail={"code": "DEVICE_NOT_FOUND", "message": "待解绑设备不存在"}
            )
        await _unbind_single_device(db, device)
    else:
        devices = await list_user_devices(db, req.user_id)
        if len(devices) >= await get_device_bind_limit():
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "UNBIND_TARGET_REQUIRED", "message": "设备已满，请选择要解绑的旧设备"},
            )
    req.status = "approved"
    req.resolved_at = datetime.now(UTC)
    req.resolved_by = admin_id
    await db.commit()
    await write_audit(
        "device_request_approved",
        user_id=admin_id,
        detail=f"target={req.user_id},device={req.device_key[:8]},unbind={(body.unbindDeviceId or '')[:8]}",
    )
    return {"ok": True, "status": "approved"}


@router.post("/device-requests/{request_id}/reject")
async def reject_device_request(
    request_id: str,
    admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    req = await db.get(DeviceBindRequest, request_id)
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "REQUEST_NOT_FOUND", "message": "申请不存在"})
    if req.status != "pending":
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail={"code": "REQUEST_RESOLVED", "message": "该申请已处理"}
        )
    req.status = "rejected"
    req.resolved_at = datetime.now(UTC)
    req.resolved_by = admin_id
    await db.commit()
    await write_audit(
        "device_request_rejected", user_id=admin_id, detail=f"target={req.user_id},device={req.device_key[:8]}"
    )
    return {"ok": True, "status": "rejected"}


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
