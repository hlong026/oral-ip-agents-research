"""activation 业务编排（激活码注册 / 兑换 / 批量生码 / 作废 / 订阅升级与到期处理）

认证策略：
- 激活码是开户唯一入口，激活时绑定手机号 + 密码
- 禁止通过手机号直接注册
- 已登录用户可兑换新码进行续费或套餐升级

安全：HMAC 签名校验 + 一码一户 + 频率限制
"""

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import create_access_token, create_refresh_token, decode_token, hash_password

from . import code_generator
from . import repository as repo
from .models import ActivationBatch, ActivationCode, UserSubscription
from .schemas import (
    ActivateOut,
    BatchGenerateOut,
    CodeInfoOut,
    CodeStatsOut,
    RedeemOut,
    SubscriptionOut,
)

logger = get_logger("oral.activation")
settings = get_settings()

# 套餐映射
PLAN_NAMES = {
    "trial": "体验码",
    "monthly": "月卡",
    "quarterly": "季卡",
    "yearly": "年卡",
    "points": "点数包",
}


def _normalize_code(raw: str) -> str:
    """标准化激活码格式"""
    return raw.strip().upper().replace(" ", "")


def _validate_code_or_raise(code_str: str) -> None:
    """HMAC 签名校验（防伪造）"""
    if not code_generator.verify_code_format(code_str):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_CODE", "message": "激活码无效或格式错误"},
        )


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _code_expired(expires_at: datetime | None) -> bool:
    normalized = _as_utc(expires_at)
    return normalized is not None and normalized < datetime.now(UTC)


def _plan_available(plan, *, honor_existing_sale: bool = False) -> bool:
    if plan.status == "published" or (honor_existing_sale and plan.status == "retired"):
        return True
    effective_at = _as_utc(plan.effective_at)
    return plan.status == "scheduled" and effective_at is not None and effective_at <= datetime.now(UTC)


async def validate_code(db: AsyncSession, raw_code: str) -> CodeInfoOut:
    """预校验码有效性（前端实时反馈）"""
    code_str = _normalize_code(raw_code)
    # 签名校验
    if not code_generator.verify_code_format(code_str):
        return CodeInfoOut(valid=False, message="激活码格式无效")
    # DB 查询
    code = await repo.get_code_by_value(db, code_str)
    if not code:
        return CodeInfoOut(valid=False, message="激活码不存在")
    if code.status == "used":
        return CodeInfoOut(valid=False, message="激活码已被使用")
    if code.status == "revoked":
        return CodeInfoOut(valid=False, message="激活码已作废")
    if code.status == "expired":
        return CodeInfoOut(valid=False, message="激活码已过期")
    if _code_expired(code.expires_at):
        return CodeInfoOut(valid=False, message="激活码已过期")
    plan_type = code.plan_type
    quota_amount = code.quota_amount
    duration_days = code.duration_days
    if code.sku_version_id:
        from app.modules.catalog import repository as catalog_repo

        plan = await catalog_repo.get_plan_version(db, code.sku_version_id)
        if plan:
            plan_type = plan.sku_type
            quota_amount = float(plan.monthly_points or plan.one_time_points)
            duration_days = plan.duration_days
    return CodeInfoOut(
        valid=True,
        planType=plan_type,
        quotaAmount=quota_amount,
        durationDays=duration_days,
        message=f"{PLAN_NAMES.get(plan_type, plan_type)} · {quota_amount:.0f} 点数 · {duration_days} 天",
    )


async def activate(
    db: AsyncSession,
    code_str: str,
    phone: str,
    password: str,
    nickname: str,
    device_fingerprint: str,
) -> ActivateOut:
    """激活码注册（首次开户）"""
    code_str = _normalize_code(code_str)
    # 1. HMAC 签名校验
    _validate_code_or_raise(code_str)

    # 2. 查码状态
    code = await repo.get_code_by_value(db, code_str)
    if not code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail={"code": "INVALID_CODE", "message": "激活码不存在"})
    if code.status != "unused":
        msg = {"used": "激活码已被使用", "revoked": "激活码已作废", "expired": "激活码已过期"}.get(
            code.status, "激活码不可用"
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail={"code": "CODE_UNAVAILABLE", "message": msg})
    if _code_expired(code.expires_at):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail={"code": "CODE_EXPIRED", "message": "激活码已过期"})

    # 3. 手机号唯一性
    from app.modules.auth import repository as auth_repo

    if await auth_repo.get_by_phone(db, phone):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "PHONE_TAKEN", "message": "该手机号已注册，请直接登录后兑换激活码"},
        )

    # 4. 原子性消耗激活码（CAS 防并发）
    consumed = await repo.mark_code_used(db, code.id, "__pending__")
    if not consumed:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail={"code": "CODE_UNAVAILABLE", "message": "激活码已被使用"}
        )

    # 5. 创建用户（不单独 commit，保持事务原子性）
    from app.modules.auth.models import User

    now = datetime.now(UTC)
    plan_type = code.plan_type
    quota_amount = code.quota_amount
    duration_days = code.duration_days
    plan_sku_code = code.plan_sku_code
    monthly_points = 0
    if code.sku_version_id:
        from app.modules.catalog import repository as catalog_repo

        plan = await catalog_repo.get_plan_version(db, code.sku_version_id)
        if not plan or not _plan_available(plan, honor_existing_sale=True):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail={"code": "SKU_UNAVAILABLE", "message": "套餐不可用"},
            )
        plan_type = plan.sku_type
        if plan_type == "points_pack":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail={"code": "POINTS_PACK_REQUIRES_ACCOUNT", "message": "积分包只能由已有用户登录后兑换"},
            )
        duration_days = plan.duration_days
        monthly_points = plan.monthly_points
        quota_amount = float(plan.monthly_points if plan.monthly_points > 0 else plan.one_time_points)
        plan_sku_code = plan.code
    plan_expires = now + timedelta(days=duration_days) if duration_days > 0 else None

    user = User(
        phone=phone,
        password_hash=hash_password(password),
        nickname=nickname or phone[-4:],
        avatar_char=(nickname or phone)[0],
        activated_at=now,
        plan_type=plan_type,
        plan_sku_code=plan_sku_code,
        plan_expires_at=plan_expires,
        device_fingerprint=device_fingerprint,
    )
    db.add(user)
    await db.flush()  # 获取 user.id

    # 6. 更新码绑定到真实 user_id
    from sqlalchemy import update as sa_update

    from .models import ActivationCode

    await db.execute(sa_update(ActivationCode).where(ActivationCode.id == code.id).values(bound_user_id=user.id))
    if code.batch_id:
        await repo.increment_batch_used(db, code.batch_id)

    # 7. 发放额度
    from app.modules.billing.service import grant_points

    acc = await grant_points(
        db,
        user.id,
        int(quota_amount),
        source_type="points_pack" if plan_type == "points_pack" else "plan",
        source_id=code.id,
        expires_at=(now + timedelta(days=365)) if plan_type == "points_pack" else plan_expires,
    )

    # 8. 订阅记录
    next_grant_at = now + timedelta(days=30) if monthly_points > 0 else None
    if next_grant_at and plan_expires and next_grant_at >= plan_expires:
        next_grant_at = None
    await repo.add_subscription(
        db,
        UserSubscription(
            user_id=user.id,
            code_id=code.id,
            plan_type=plan_type,
            sku_version_id=code.sku_version_id,
            plan_sku_code=plan_sku_code,
            quota_granted=quota_amount,
            duration_days=duration_days,
            monthly_points=monthly_points,
            grants_issued=1 if monthly_points > 0 else 0,
            next_grant_at=next_grant_at,
            expires_at=plan_expires,
        ),
    )

    # 9. 默认 IP 档案
    from app.modules.ipasset.service import create_default_persona

    await create_default_persona(db, user.id, user.nickname)

    # 10. 签发 JWT + 保存 session（不单独 commit）
    from app.modules.auth.models import RefreshSession

    device = device_fingerprint or "web"
    access_token = create_access_token(user.id, device)
    refresh_token = create_refresh_token(user.id, device)
    payload = decode_token(refresh_token, "refresh")
    if payload:
        db.add(RefreshSession(user_id=user.id, device_id=device, refresh_jti=str(payload["jti"])))

    await db.commit()

    # 11. 审计日志
    logger.info("activation_success", user_id=user.id, phone=phone, plan=plan_type, code_id=code.id)
    await write_audit(
        "activation_success", user_id=user.id, detail=f"phone={phone},plan={plan_type},quota={quota_amount}"
    )

    return ActivateOut(
        accessToken=access_token,
        refreshToken=refresh_token,
        expiresIn=settings.access_token_ttl_min * 60,
        planType=plan_type,
        planSkuCode=plan_sku_code,
        planExpiresAt=plan_expires.isoformat() if plan_expires else None,
        quotaBalance=acc.balance,
    )


async def redeem(db: AsyncSession, user_id: str, raw_code: str) -> RedeemOut:
    """已登录用户兑换新码（续费/充值）"""
    code_str = _normalize_code(raw_code)
    _validate_code_or_raise(code_str)

    code = await repo.get_code_by_value(db, code_str)
    if not code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail={"code": "INVALID_CODE", "message": "激活码不存在"})
    if code.status != "unused":
        msg = {"used": "激活码已被使用", "revoked": "激活码已作废", "expired": "激活码已过期"}.get(
            code.status, "激活码不可用"
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail={"code": "CODE_UNAVAILABLE", "message": msg})
    if _code_expired(code.expires_at):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail={"code": "CODE_EXPIRED", "message": "激活码已过期"})

    now = datetime.now(UTC)
    plan_type = code.plan_type
    quota_amount = code.quota_amount
    duration_days = code.duration_days
    plan_sku_code = code.plan_sku_code
    monthly_points = 0
    if code.sku_version_id:
        from app.modules.catalog import repository as catalog_repo

        plan = await catalog_repo.get_plan_version(db, code.sku_version_id)
        if not plan or not _plan_available(plan, honor_existing_sale=True):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail={"code": "SKU_UNAVAILABLE", "message": "套餐不可用"},
            )
        plan_type = plan.sku_type
        monthly_points = plan.monthly_points
        quota_amount = float(plan.monthly_points if plan.monthly_points > 0 else plan.one_time_points)
        duration_days = plan.duration_days
        plan_sku_code = plan.code
    # 原子性消耗码（CAS 防并发）
    consumed = await repo.mark_code_used(db, code.id, user_id)
    if not consumed:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail={"code": "CODE_UNAVAILABLE", "message": "激活码已被使用"}
        )
    if code.batch_id:
        await repo.increment_batch_used(db, code.batch_id)

    # 追加额度
    # 续期：取 max(当前到期, now) + duration
    from app.modules.auth import repository as auth_repo

    user = await auth_repo.get_by_id(db, user_id)
    previous_plan = (getattr(user, "plan_type", "none") or "none") if user else "none"
    upgrade = is_upgrade(previous_plan, plan_type)
    new_expires: datetime | None
    if user and duration_days > 0:
        current_expires = _as_utc(getattr(user, "plan_expires_at", None))
        base = max(current_expires, now) if current_expires and current_expires > now else now
        new_expires = base + timedelta(days=duration_days)
        user.plan_expires_at = new_expires  # type: ignore[attr-defined]
        user.plan_type = plan_type  # type: ignore[attr-defined]
        user.plan_sku_code = plan_sku_code  # type: ignore[attr-defined]
    else:
        new_expires = getattr(user, "plan_expires_at", None) if user else None

    from app.modules.billing.service import grant_points

    acc = await grant_points(
        db,
        user_id,
        int(quota_amount),
        source_type="points_pack" if plan_type == "points_pack" else "plan",
        source_id=code.id,
        expires_at=(now + timedelta(days=365)) if plan_type == "points_pack" else new_expires,
    )

    # 订阅记录
    next_grant_at = now + timedelta(days=30) if monthly_points > 0 else None
    normalized_new_expires = _as_utc(new_expires)
    if next_grant_at and normalized_new_expires and next_grant_at >= normalized_new_expires:
        next_grant_at = None
    if duration_days > 0:
        await db.execute(
            update(UserSubscription)
            .where(
                UserSubscription.user_id == user_id,
                UserSubscription.next_grant_at.is_not(None),
            )
            .values(next_grant_at=None)
        )
    await repo.add_subscription(
        db,
        UserSubscription(
            user_id=user_id,
            code_id=code.id,
            plan_type=plan_type,
            sku_version_id=code.sku_version_id,
            plan_sku_code=plan_sku_code,
            quota_granted=quota_amount,
            duration_days=duration_days,
            monthly_points=monthly_points,
            grants_issued=1 if monthly_points > 0 else 0,
            next_grant_at=next_grant_at,
            expires_at=new_expires,
        ),
    )

    await db.commit()

    logger.info("redeem_success", user_id=user_id, plan=plan_type, quota=quota_amount, upgrade=upgrade)
    await write_audit(
        "redeem_success",
        user_id=user_id,
        detail=f"plan={plan_type},quota={quota_amount},upgrade={upgrade}",
    )

    return RedeemOut(
        planType=plan_type,
        planSkuCode=plan_sku_code,
        planExpiresAt=new_expires.isoformat() if new_expires else None,
        quotaGranted=quota_amount,
        newBalance=acc.balance,
        isUpgrade=upgrade,
        previousPlanType=previous_plan,
    )


async def grant_due_subscription_points(db: AsyncSession, user_id: str) -> None:
    """按订阅周期幂等补发到期月度积分；用户访问和服务启动时均可安全调用。"""
    now = datetime.now(UTC)
    subscriptions = list(
        (
            await db.execute(
                select(UserSubscription).where(
                    UserSubscription.user_id == user_id,
                    UserSubscription.monthly_points > 0,
                    UserSubscription.next_grant_at.is_not(None),
                    UserSubscription.next_grant_at <= now,
                )
            )
        )
        .scalars()
        .all()
    )
    changed = False
    from app.modules.billing.service import grant_points

    for subscription in subscriptions:
        next_grant_at = _as_utc(subscription.next_grant_at)
        expires_at = _as_utc(subscription.expires_at)
        if next_grant_at is None or expires_at is None:
            continue
        subscription_expires_at: datetime = expires_at
        while next_grant_at is not None:
            if next_grant_at > now or next_grant_at >= subscription_expires_at:
                break
            candidate = next_grant_at + timedelta(days=30)
            following: datetime | None = None if candidate >= subscription_expires_at else candidate
            claimed = await db.execute(
                update(UserSubscription)
                .where(
                    UserSubscription.id == subscription.id,
                    UserSubscription.next_grant_at == subscription.next_grant_at,
                )
                .values(
                    next_grant_at=following,
                    grants_issued=UserSubscription.grants_issued + 1,
                )
                .execution_options(synchronize_session=False)
            )
            if int(getattr(claimed, "rowcount", 0) or 0) != 1:
                await db.rollback()
                return
            grant_number = subscription.grants_issued + 1
            await grant_points(
                db,
                user_id,
                subscription.monthly_points,
                source_type="plan_monthly",
                source_id=f"{subscription.id}:month:{grant_number}",
                expires_at=subscription_expires_at,
            )
            subscription.grants_issued = grant_number
            subscription.next_grant_at = following
            next_grant_at = following
            changed = True
    if changed:
        await db.commit()


async def get_subscription(db: AsyncSession, user_id: str) -> SubscriptionOut:
    """查询当前订阅状态，并补发已到周期但尚未领取的月度积分。"""
    from app.modules.auth import repository as auth_repo
    from app.modules.billing import repository as billing_repo

    await grant_due_subscription_points(db, user_id)
    user = await auth_repo.get_by_id(db, user_id)
    acc = await billing_repo.ensure_account(db, user_id)
    subscriptions = await repo.get_user_subscriptions(db, user_id)
    current = next((item for item in subscriptions if item.duration_days > 0), None)
    plan_name: str | None = None
    if current and current.sku_version_id:
        from app.modules.catalog import repository as catalog_repo

        plan = await catalog_repo.get_plan_version(db, current.sku_version_id)
        plan_name = plan.name if plan else None

    plan_type = getattr(user, "plan_type", "none") if user else "none"
    plan_expires = getattr(user, "plan_expires_at", None) if user else None
    activated_at = getattr(user, "activated_at", None) if user else None

    return SubscriptionOut(
        planType=plan_type or "none",
        planSkuCode=getattr(user, "plan_sku_code", "") if user else "",
        planName=plan_name,
        planExpiresAt=plan_expires.isoformat() if plan_expires else None,
        activatedAt=activated_at.isoformat() if activated_at else None,
        nextGrantAt=current.next_grant_at.isoformat() if current and current.next_grant_at else None,
        monthlyPoints=current.monthly_points if current else 0,
        quotaBalance=acc.balance,
    )


# ---------- 管理侧 ----------


async def generate_batch(
    db: AsyncSession,
    name: str,
    plan_type: str,
    quota_amount: float,
    duration_days: int,
    count: int,
    channel: str,
    code_expires_at: str | None,
    created_by: str = "",
    sku_version_id: str | None = None,
) -> BatchGenerateOut:
    """批量生成激活码"""
    plan_sku_code = ""
    if not sku_version_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "SKU_VERSION_REQUIRED", "message": "激活码批次必须绑定已发布套餐版本"},
        )
    from app.modules.catalog import repository as catalog_repo

    await catalog_repo.promote_due_plan_versions(db)
    plan = await catalog_repo.get_plan_version(db, sku_version_id)
    if not plan or not _plan_available(plan):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "SKU_VERSION_NOT_PUBLISHED", "message": "只能使用已发布套餐生成激活码"},
        )
    plan_type = plan.sku_type
    quota_amount = float(plan.monthly_points if plan.monthly_points > 0 else plan.one_time_points)
    duration_days = plan.duration_days
    plan_sku_code = plan.code
    # 创建批次
    expires_dt = datetime.fromisoformat(code_expires_at) if code_expires_at else None
    batch = await repo.create_batch(
        db,
        ActivationBatch(
            name=name,
            plan_type=plan_type,
            quota_amount=quota_amount,
            duration_days=duration_days,
            sku_version_id=sku_version_id or "",
            plan_sku_code=plan_sku_code,
            total_count=count,
            channel=channel,
            code_expires_at=expires_dt,
            created_by=created_by,
        ),
    )

    # 生成码
    raw_codes = code_generator.generate_batch(count)
    code_objs = [
        ActivationCode(
            code=code_generator.hash_code(c),
            plan_type=plan_type,
            quota_amount=quota_amount,
            duration_days=duration_days,
            sku_version_id=sku_version_id or "",
            plan_sku_code=plan_sku_code,
            batch_id=batch.id,
            channel=channel,
            expires_at=expires_dt,
        )
        for c in raw_codes
    ]
    await repo.create_codes(db, code_objs)
    await db.commit()

    logger.info("batch_generated", batch_id=batch.id, count=count, plan=plan_type)
    await write_audit(
        "activation_batch_generated",
        user_id=created_by,
        detail=f"batch={batch.id},sku_version={sku_version_id or ''},count={count},channel={channel}",
    )
    return BatchGenerateOut(batchId=batch.id, generated=count, codes=raw_codes)


async def revoke_code_by_id(db: AsyncSession, code_id: str, admin_id: str) -> None:
    ok = await repo.revoke_code(db, code_id)
    if not ok:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail={"code": "REVOKE_FAILED", "message": "码不存在或已使用，无法作废"}
        )
    await db.commit()
    await write_audit("activation_code_revoked", user_id=admin_id, detail=f"code_id={code_id}")


async def revoke_batch_codes(db: AsyncSession, batch_id: str, admin_id: str) -> int:
    count = await repo.revoke_batch(db, batch_id)
    await db.commit()
    await write_audit(
        "activation_batch_revoked",
        user_id=admin_id,
        detail=f"batch_id={batch_id},count={count}",
    )
    return count


async def get_stats(db: AsyncSession) -> CodeStatsOut:
    stats = await repo.code_stats(db)
    return CodeStatsOut(**stats)


# ---------- 订阅升级与到期处理 ----------

# 套餐层级（数字越大等级越高，用于升级判断）
PLAN_TIER: dict[str, int] = {
    "none": 0,
    "trial": 1,
    "points": 1,
    "points_pack": 1,
    "monthly": 2,
    "quarterly": 3,
    "yearly": 4,
    "annual_bundle": 4,
}


def _plan_tier(plan_type: str) -> int:
    return PLAN_TIER.get(plan_type, 0)


def is_upgrade(current_plan: str, new_plan: str) -> bool:
    """判断新套餐是否为升级（层级更高）"""
    return _plan_tier(new_plan) > _plan_tier(current_plan)


async def handle_subscription_expiry(db: AsyncSession, user_id: str) -> None:
    """检查并处理用户订阅到期：将 plan_type 置为 none，保留积分余额不清零。

    可在用户登录、访问订阅状态或定时任务中安全调用（幂等）。
    """
    from app.modules.auth import repository as auth_repo

    user = await auth_repo.get_by_id(db, user_id)
    if not user:
        return
    plan_expires = _as_utc(getattr(user, "plan_expires_at", None))
    if plan_expires is None:
        return
    now = datetime.now(UTC)
    if plan_expires > now:
        return
    # 已到期：降级为 none
    current_plan = getattr(user, "plan_type", "none") or "none"
    if current_plan == "none":
        return
    user.plan_type = "none"  # type: ignore[attr-defined]
    await db.commit()
    logger.info("subscription_expired", user_id=user_id, old_plan=current_plan)
    await write_audit("subscription_expired", user_id=user_id, detail=f"old_plan={current_plan}")


async def get_subscription_with_expiry_check(db: AsyncSession, user_id: str) -> SubscriptionOut:
    """查询订阅状态（先检查到期，再返回结果）"""
    await handle_subscription_expiry(db, user_id)
    return await get_subscription(db, user_id)
