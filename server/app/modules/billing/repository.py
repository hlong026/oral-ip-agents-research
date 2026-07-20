"""billing 数据访问"""
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import DEFAULT_PRICES, QuotaAccount, QuotaPrice, QuotaUsage


async def get_account(db: AsyncSession, user_id: str) -> QuotaAccount | None:
    res = await db.execute(select(QuotaAccount).where(QuotaAccount.user_id == user_id))
    return res.scalar_one_or_none()


async def ensure_account(db: AsyncSession, user_id: str) -> QuotaAccount:
    acc = await get_account(db, user_id)
    if acc is None:
        acc = QuotaAccount(user_id=user_id)
        db.add(acc)
        await db.commit()
        await db.refresh(acc)
    return acc


async def seed_prices(db: AsyncSession) -> None:
    res = await db.execute(select(func.count(QuotaPrice.id)))
    if (res.scalar() or 0) > 0:
        return
    for step, reso, price in DEFAULT_PRICES:
        db.add(QuotaPrice(step=step, resolution=reso, unit_price=price))
    await db.commit()


async def price_of(db: AsyncSession, step: str, resolution: str = "1080p") -> float:
    res = await db.execute(
        select(QuotaPrice.unit_price).where(QuotaPrice.step == step, QuotaPrice.resolution == resolution)
    )
    return float(res.scalar_one_or_none() or 0)


async def add_usage(db: AsyncSession, usage: QuotaUsage) -> QuotaUsage:
    db.add(usage)
    await db.commit()
    await db.refresh(usage)
    return usage


async def list_usage(db: AsyncSession, user_id: str, page: int, page_size: int) -> tuple[list[QuotaUsage], int]:
    total = (
        await db.execute(select(func.count(QuotaUsage.id)).where(QuotaUsage.user_id == user_id))
    ).scalar() or 0
    res = await db.execute(
        select(QuotaUsage)
        .where(QuotaUsage.user_id == user_id)
        .order_by(QuotaUsage.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(res.scalars().all()), int(total)


async def all_usage(db: AsyncSession, user_id: str) -> list[QuotaUsage]:
    res = await db.execute(
        select(QuotaUsage).where(QuotaUsage.user_id == user_id).order_by(QuotaUsage.created_at.desc())
    )
    return list(res.scalars().all())


def month_start() -> datetime:
    now = datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
