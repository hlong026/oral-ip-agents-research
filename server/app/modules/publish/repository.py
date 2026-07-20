"""publish 数据访问"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import PublishAccount, PublishJob


async def create_account(db: AsyncSession, **fields) -> PublishAccount:
    a = PublishAccount(**fields)
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


async def get_account(db: AsyncSession, account_id: str, user_id: str | None = None) -> PublishAccount | None:
    q = select(PublishAccount).where(PublishAccount.id == account_id)
    if user_id:
        q = q.where(PublishAccount.user_id == user_id)
    res = await db.execute(q)
    return res.scalar_one_or_none()


async def list_accounts(db: AsyncSession, user_id: str) -> list[PublishAccount]:
    res = await db.execute(
        select(PublishAccount).where(PublishAccount.user_id == user_id)
        .order_by(PublishAccount.created_at.desc()))
    return list(res.scalars().all())


async def active_account_for(db: AsyncSession, user_id: str, platform: str) -> PublishAccount | None:
    res = await db.execute(
        select(PublishAccount)
        .where(PublishAccount.user_id == user_id,
               PublishAccount.platform == platform,
               PublishAccount.status == "active")
        .order_by(PublishAccount.created_at.desc()).limit(1))
    return res.scalar_one_or_none()


async def save_account(db: AsyncSession, account: PublishAccount) -> PublishAccount:
    await db.commit()
    await db.refresh(account)
    return account


async def delete_account(db: AsyncSession, account: PublishAccount) -> None:
    await db.delete(account)
    await db.commit()


async def create_job(db: AsyncSession, **fields) -> PublishJob:
    j = PublishJob(**fields)
    db.add(j)
    await db.commit()
    await db.refresh(j)
    return j


async def get_job(db: AsyncSession, job_id: str, user_id: str | None = None) -> PublishJob | None:
    q = select(PublishJob).where(PublishJob.id == job_id)
    if user_id:
        q = q.where(PublishJob.user_id == user_id)
    res = await db.execute(q)
    return res.scalar_one_or_none()


async def save_job(db: AsyncSession, job: PublishJob) -> PublishJob:
    await db.commit()
    await db.refresh(job)
    return job


async def list_jobs(db: AsyncSession, user_id: str, status: str | None,
                    page: int, page_size: int) -> tuple[list[PublishJob], int]:
    cond = PublishJob.user_id == user_id
    if status:
        cond = cond & (PublishJob.status == status)
    total = (await db.execute(select(func.count(PublishJob.id)).where(cond))).scalar() or 0
    res = await db.execute(
        select(PublishJob).where(cond)
        .order_by(PublishJob.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size))
    return list(res.scalars().all()), int(total)
