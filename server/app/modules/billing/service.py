"""
billing 业务编排（F-602 / §11.2）
- 扣费语义：步骤成功后扣费、失败自动退还
- 本地通道执行的步骤免扣额度
- 日志：扣费/退款/额度耗尽（§10.6.8-A #2，安全审计 DB 双写）
"""
from datetime import UTC

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import CHANNEL_ALERT, publish
from app.core.logging import get_logger

from . import repository as repo
from .models import QuotaUsage
from .schemas import QuotaOut, UsageItemOut

logger = get_logger("oral.billing")
INITIAL_GRANT = 12430.0  # 开户礼点数（对齐效果图额度卡）


async def grant_initial_quota(db: AsyncSession, user_id: str) -> None:
    acc = await repo.ensure_account(db, user_id)
    acc.balance += INITIAL_GRANT
    acc.total_granted += INITIAL_GRANT
    await db.commit()


async def get_quota(db: AsyncSession, user_id: str) -> QuotaOut:
    acc = await repo.ensure_account(db, user_id)
    return QuotaOut(balance=acc.balance, usedThisMonth=acc.used_this_month, total=acc.total_granted)


async def charge(
    db: AsyncSession,
    user_id: str,
    trace_id: str,
    task_id: str,
    step: str,
    compute: str = "cloud",
    resolution: str = "1080p",
) -> float:
    """步骤成功扣费；本地通道免扣（返回 0）。额度不足抛 402。"""
    if compute == "local":
        await repo.add_usage(db, QuotaUsage(user_id=user_id, trace_id=trace_id, task_id=task_id,
                                            step=step, resolution=resolution, points=0, compute="local"))
        return 0.0
    price = await repo.price_of(db, step, resolution)
    acc = await repo.ensure_account(db, user_id)
    if acc.balance < price:
        # 额度不足：记录 WARNING（安全审计）
        logger.warning(
            "quota_exhausted",
            user_id=user_id,
            trace_id=trace_id,
            task_id=task_id,
            step=step,
            balance=acc.balance,
            required=price,
        )
        await publish(CHANNEL_ALERT, {"level": "warn", "message": f"额度不足，步骤 {step} 扣费失败",
                                      "userId": user_id, "traceId": trace_id})
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED,
                            detail={"code": "QUOTA_EXHAUSTED", "message": "算力额度不足，请充值"})
    acc.balance -= price
    acc.used_this_month += price
    await db.commit()
    await repo.add_usage(db, QuotaUsage(user_id=user_id, trace_id=trace_id, task_id=task_id,
                                        step=step, resolution=resolution, points=price, compute=compute))
    # 扣费成功：记录 INFO（安全审计）
    logger.info(
        "quota_charged",
        user_id=user_id,
        trace_id=trace_id,
        task_id=task_id,
        step=step,
        points=price,
        balance_after=acc.balance,
    )
    return price


async def refund(db: AsyncSession, user_id: str, trace_id: str, task_id: str, step: str,
                 compute: str = "cloud", resolution: str = "1080p") -> None:
    """失败退还（对齐云厂商“失败不扣费”惯例）"""
    if compute == "local":
        return
    price = await repo.price_of(db, step, resolution)
    if price <= 0:
        return
    acc = await repo.ensure_account(db, user_id)
    acc.balance += price
    acc.used_this_month = max(0.0, acc.used_this_month - price)
    await db.commit()
    await repo.add_usage(db, QuotaUsage(user_id=user_id, trace_id=trace_id, task_id=task_id,
                                        step=step, resolution=resolution, points=-price, compute=compute))
    # 退款成功：记录 INFO（安全审计）
    logger.info(
        "quota_refunded",
        user_id=user_id,
        trace_id=trace_id,
        task_id=task_id,
        step=step,
        points=price,
        balance_after=acc.balance,
    )


def usage_to_out(u: QuotaUsage) -> UsageItemOut:
    return UsageItemOut(
        id=u.id,
        traceId=u.trace_id,
        step=u.step,
        resolution=u.resolution,
        points=u.points,
        compute=u.compute,
        createdAt=u.created_at.astimezone(UTC).isoformat(),
    )
