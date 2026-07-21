"""activation 数据访问层"""

from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ActivationBatch, ActivationCode, UserSubscription


async def get_code_by_value(db: AsyncSession, code: str) -> ActivationCode | None:
    from .code_generator import hash_code

    digest = hash_code(code)
    res = await db.execute(select(ActivationCode).where(ActivationCode.code.in_([digest, code])))
    return res.scalar_one_or_none()


async def mark_code_used(db: AsyncSession, code_id: str, user_id: str) -> bool:
    """原子性 CAS 消耗激活码（防并发双重兑换）"""
    res = await db.execute(
        update(ActivationCode)
        .where(ActivationCode.id == code_id, ActivationCode.status == "unused")
        .values(status="used", bound_user_id=user_id, activated_at=datetime.now(UTC))
    )
    return int(getattr(res, "rowcount", 0) or 0) > 0


async def create_codes(db: AsyncSession, codes: list[ActivationCode]) -> None:
    db.add_all(codes)
    await db.flush()


async def create_batch(db: AsyncSession, batch: ActivationBatch) -> ActivationBatch:
    db.add(batch)
    await db.flush()
    await db.refresh(batch)
    return batch


async def increment_batch_used(db: AsyncSession, batch_id: str) -> None:
    await db.execute(
        update(ActivationBatch).where(ActivationBatch.id == batch_id).values(used_count=ActivationBatch.used_count + 1)
    )


async def add_subscription(db: AsyncSession, sub: UserSubscription) -> None:
    db.add(sub)
    await db.flush()


async def list_codes(
    db: AsyncSession,
    status: str | None = None,
    batch_id: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[ActivationCode], int]:
    q = select(ActivationCode)
    if status:
        q = q.where(ActivationCode.status == status)
    if batch_id:
        q = q.where(ActivationCode.batch_id == batch_id)
    # 总数
    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar() or 0
    # 分页
    q = q.order_by(ActivationCode.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).scalars().all()
    return list(rows), total


async def list_batches(db: AsyncSession, page: int = 1, page_size: int = 50) -> tuple[list[ActivationBatch], int]:
    count_q = select(func.count()).select_from(ActivationBatch)
    total = (await db.execute(count_q)).scalar() or 0
    q = (
        select(ActivationBatch)
        .order_by(ActivationBatch.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(q)).scalars().all()
    return list(rows), total


async def revoke_code(db: AsyncSession, code_id: str) -> bool:
    res = await db.execute(
        update(ActivationCode)
        .where(ActivationCode.id == code_id, ActivationCode.status == "unused")
        .values(status="revoked")
    )
    return int(getattr(res, "rowcount", 0) or 0) > 0


async def revoke_batch(db: AsyncSession, batch_id: str) -> int:
    res = await db.execute(
        update(ActivationCode)
        .where(ActivationCode.batch_id == batch_id, ActivationCode.status == "unused")
        .values(status="revoked")
    )
    return int(getattr(res, "rowcount", 0) or 0)


async def code_stats(db: AsyncSession) -> dict[str, int]:
    rows = await db.execute(select(ActivationCode.status, func.count()).group_by(ActivationCode.status))
    stats = {row[0]: row[1] for row in rows.all()}
    return {
        "total": sum(stats.values()),
        "unused": stats.get("unused", 0),
        "used": stats.get("used", 0),
        "expired": stats.get("expired", 0),
        "revoked": stats.get("revoked", 0),
    }


async def get_user_subscriptions(db: AsyncSession, user_id: str) -> list[UserSubscription]:
    res = await db.execute(
        select(UserSubscription)
        .where(UserSubscription.user_id == user_id)
        .order_by(UserSubscription.activated_at.desc())
    )
    return list(res.scalars().all())
