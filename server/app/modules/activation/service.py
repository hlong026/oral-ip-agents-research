"""activation 业务编排（激活码注册 / 兑换 / 批量生码 / 作废）
安全：HMAC 签名校验 + 一码一户 + 频率限制预留
"""
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import create_access_token, create_refresh_token, decode_token, hash_password

from . import code_generator, repository as repo
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
    if code.expires_at and code.expires_at < datetime.now(UTC):
        return CodeInfoOut(valid=False, message="激活码已过期")
    return CodeInfoOut(
        valid=True,
        planType=code.plan_type,
        quotaAmount=code.quota_amount,
        durationDays=code.duration_days,
        message=f"{PLAN_NAMES.get(code.plan_type, code.plan_type)} · {code.quota_amount:.0f} 点数 · {code.duration_days} 天",
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
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail={"code": "INVALID_CODE", "message": "激活码不存在"})
    if code.status != "unused":
        msg = {"used": "激活码已被使用", "revoked": "激活码已作废", "expired": "激活码已过期"}.get(
            code.status, "激活码不可用")
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail={"code": "CODE_UNAVAILABLE", "message": msg})
    if code.expires_at and code.expires_at < datetime.now(UTC):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail={"code": "CODE_EXPIRED", "message": "激活码已过期"})

    # 3. 手机号唯一性
    from app.modules.auth import repository as auth_repo
    if await auth_repo.get_by_phone(db, phone):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"code": "PHONE_TAKEN", "message": "该手机号已注册，请直接登录后兑换激活码"})

    # 4. 原子性消耗激活码（CAS 防并发）
    consumed = await repo.mark_code_used(db, code.id, "__pending__")
    if not consumed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail={"code": "CODE_UNAVAILABLE", "message": "激活码已被使用"})

    # 5. 创建用户（不单独 commit，保持事务原子性）
    from app.modules.auth.models import User
    now = datetime.now(UTC)
    plan_expires = now + timedelta(days=code.duration_days) if code.duration_days > 0 else None

    user = User(
        phone=phone,
        password_hash=hash_password(password),
        nickname=nickname or phone[-4:],
        avatar_char=(nickname or phone)[0],
        activated_at=now,
        plan_type=code.plan_type,
        plan_expires_at=plan_expires,
        device_fingerprint=device_fingerprint,
    )
    db.add(user)
    await db.flush()  # 获取 user.id

    # 6. 更新码绑定到真实 user_id
    from sqlalchemy import update as sa_update
    from .models import ActivationCode
    await db.execute(
        sa_update(ActivationCode)
        .where(ActivationCode.id == code.id)
        .values(bound_user_id=user.id)
    )
    if code.batch_id:
        await repo.increment_batch_used(db, code.batch_id)

    # 7. 发放额度
    from app.modules.billing import repository as billing_repo
    acc = await billing_repo.ensure_account(db, user.id)
    acc.balance += code.quota_amount
    acc.total_granted += code.quota_amount

    # 8. 订阅记录
    await repo.add_subscription(db, UserSubscription(
        user_id=user.id, code_id=code.id, plan_type=code.plan_type,
        quota_granted=code.quota_amount, duration_days=code.duration_days,
    ))

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
    logger.info("activation_success", user_id=user.id, phone=phone, plan=code.plan_type, code_id=code.id)
    await write_audit("activation_success", user_id=user.id,
                      detail=f"phone={phone},plan={code.plan_type},quota={code.quota_amount}")

    return ActivateOut(
        accessToken=access_token,
        refreshToken=refresh_token,
        expiresIn=settings.access_token_ttl_min * 60,
        planType=code.plan_type,
        planExpiresAt=plan_expires.isoformat() if plan_expires else None,
        quotaBalance=code.quota_amount,
    )


async def redeem(db: AsyncSession, user_id: str, raw_code: str) -> RedeemOut:
    """已登录用户兑换新码（续费/充值）"""
    code_str = _normalize_code(raw_code)
    _validate_code_or_raise(code_str)

    code = await repo.get_code_by_value(db, code_str)
    if not code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail={"code": "INVALID_CODE", "message": "激活码不存在"})
    if code.status != "unused":
        msg = {"used": "激活码已被使用", "revoked": "激活码已作废", "expired": "激活码已过期"}.get(
            code.status, "激活码不可用")
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail={"code": "CODE_UNAVAILABLE", "message": msg})
    if code.expires_at and code.expires_at < datetime.now(UTC):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail={"code": "CODE_EXPIRED", "message": "激活码已过期"})

    now = datetime.now(UTC)
    # 原子性消耗码（CAS 防并发）
    consumed = await repo.mark_code_used(db, code.id, user_id)
    if not consumed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail={"code": "CODE_UNAVAILABLE", "message": "激活码已被使用"})
    if code.batch_id:
        await repo.increment_batch_used(db, code.batch_id)

    # 追加额度
    from app.modules.billing import repository as billing_repo
    acc = await billing_repo.ensure_account(db, user_id)
    acc.balance += code.quota_amount
    acc.total_granted += code.quota_amount

    # 续期：取 max(当前到期, now) + duration
    from app.modules.auth import repository as auth_repo
    user = await auth_repo.get_by_id(db, user_id)
    if user and code.duration_days > 0:
        current_expires = getattr(user, "plan_expires_at", None)
        base = max(current_expires, now) if current_expires and current_expires > now else now
        new_expires = base + timedelta(days=code.duration_days)
        user.plan_expires_at = new_expires  # type: ignore[attr-defined]
        user.plan_type = code.plan_type  # type: ignore[attr-defined]
    else:
        new_expires = getattr(user, "plan_expires_at", None) if user else None

    # 订阅记录
    await repo.add_subscription(db, UserSubscription(
        user_id=user_id, code_id=code.id, plan_type=code.plan_type,
        quota_granted=code.quota_amount, duration_days=code.duration_days,
    ))

    await db.commit()

    logger.info("redeem_success", user_id=user_id, plan=code.plan_type, quota=code.quota_amount)
    await write_audit("redeem_success", user_id=user_id,
                      detail=f"plan={code.plan_type},quota={code.quota_amount}")

    return RedeemOut(
        planType=code.plan_type,
        planExpiresAt=new_expires.isoformat() if new_expires else None,
        quotaGranted=code.quota_amount,
        newBalance=acc.balance,
    )


async def get_subscription(db: AsyncSession, user_id: str) -> SubscriptionOut:
    """查询当前订阅状态"""
    from app.modules.auth import repository as auth_repo
    from app.modules.billing import repository as billing_repo

    user = await auth_repo.get_by_id(db, user_id)
    acc = await billing_repo.ensure_account(db, user_id)

    plan_type = getattr(user, "plan_type", "none") if user else "none"
    plan_expires = getattr(user, "plan_expires_at", None) if user else None
    activated_at = getattr(user, "activated_at", None) if user else None

    return SubscriptionOut(
        planType=plan_type or "none",
        planExpiresAt=plan_expires.isoformat() if plan_expires else None,
        activatedAt=activated_at.isoformat() if activated_at else None,
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
) -> BatchGenerateOut:
    """批量生成激活码"""
    # 创建批次
    expires_dt = datetime.fromisoformat(code_expires_at) if code_expires_at else None
    batch = await repo.create_batch(db, ActivationBatch(
        name=name, plan_type=plan_type, quota_amount=quota_amount,
        duration_days=duration_days, total_count=count, channel=channel,
        code_expires_at=expires_dt, created_by=created_by,
    ))

    # 生成码
    raw_codes = code_generator.generate_batch(count)
    code_objs = [
        ActivationCode(
            code=c, plan_type=plan_type, quota_amount=quota_amount,
            duration_days=duration_days, batch_id=batch.id,
            channel=channel, expires_at=expires_dt,
        )
        for c in raw_codes
    ]
    await repo.create_codes(db, code_objs)
    await db.commit()

    logger.info("batch_generated", batch_id=batch.id, count=count, plan=plan_type)
    return BatchGenerateOut(batchId=batch.id, generated=count, codes=raw_codes)


async def revoke_code_by_id(db: AsyncSession, code_id: str) -> None:
    ok = await repo.revoke_code(db, code_id)
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail={"code": "REVOKE_FAILED", "message": "码不存在或已使用，无法作废"})
    await db.commit()


async def revoke_batch_codes(db: AsyncSession, batch_id: str) -> int:
    count = await repo.revoke_batch(db, batch_id)
    await db.commit()
    return count


async def get_stats(db: AsyncSession) -> CodeStatsOut:
    stats = await repo.code_stats(db)
    return CodeStatsOut(**stats)
