"""publish 数据访问"""

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import PublishAccount, PublishJob
from .session_crypto import decode_session, encrypt_session_value, is_encrypted_session


async def create_account(db: AsyncSession, **fields) -> PublishAccount:
    fields["session_json"] = encrypt_session_value(str(fields.get("session_json") or "{}"))
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
        select(PublishAccount).where(PublishAccount.user_id == user_id).order_by(PublishAccount.created_at.desc())
    )
    return list(res.scalars().all())


async def active_account_for(db: AsyncSession, user_id: str, platform: str) -> PublishAccount | None:
    res = await db.execute(
        select(PublishAccount)
        .where(
            PublishAccount.user_id == user_id, PublishAccount.platform == platform, PublishAccount.status == "active"
        )
        .order_by(PublishAccount.created_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def active_accounts_for(db: AsyncSession, user_id: str, platform: str) -> list[PublishAccount]:
    res = await db.execute(
        select(PublishAccount)
        .where(
            PublishAccount.user_id == user_id,
            PublishAccount.platform == platform,
            PublishAccount.status == "active",
        )
        .order_by(PublishAccount.created_at.desc())
    )
    return list(res.scalars().all())


async def save_account(db: AsyncSession, account: PublishAccount) -> PublishAccount:
    account.session_json = encrypt_session_value(account.session_json)
    await db.commit()
    await db.refresh(account)
    return account


def account_session(account: PublishAccount) -> dict:
    return decode_session(account.session_json)


async def migrate_plaintext_sessions(db: AsyncSession) -> int:
    """Encrypt legacy plaintext sessions in one idempotent startup pass."""
    result = await db.execute(select(PublishAccount))
    migrated = 0
    for account in result.scalars():
        if not is_encrypted_session(account.session_json):
            account.session_json = encrypt_session_value(account.session_json)
            migrated += 1
    if migrated:
        await db.commit()
    return migrated


async def delete_account(db: AsyncSession, account: PublishAccount) -> None:
    await db.delete(account)
    await db.commit()


async def create_job(db: AsyncSession, *, commit: bool = True, **fields) -> PublishJob:
    j = PublishJob(**fields)
    db.add(j)
    if commit:
        await db.commit()
    else:
        await db.flush()
    await db.refresh(j)
    return j


async def get_task_platform_job(
    db: AsyncSession,
    user_id: str,
    task_id: str,
    platform: str,
) -> PublishJob | None:
    if not task_id:
        return None
    result = await db.execute(
        select(PublishJob)
        .where(
            PublishJob.user_id == user_id,
            PublishJob.task_id == task_id,
            PublishJob.platform == platform,
        )
        .order_by(PublishJob.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_task_render_platform_job(
    db: AsyncSession,
    user_id: str,
    task_id: str,
    render_version_id: str,
    platform: str,
) -> PublishJob | None:
    if not task_id or not render_version_id:
        return None
    return (
        await db.execute(
            select(PublishJob)
            .where(
                PublishJob.user_id == user_id,
                PublishJob.task_id == task_id,
                PublishJob.render_version_id == render_version_id,
                PublishJob.platform == platform,
            )
            .with_for_update()
            .limit(1)
        )
    ).scalar_one_or_none()


async def pin_task_render_version(
    db: AsyncSession,
    *,
    user_id: str,
    task_id: str,
    video_key: str,
    render_version_id: str,
    render_version: int,
) -> None:
    """为流水线内已创建的发布任务补齐最终结算后的成片版本。"""
    await db.execute(
        update(PublishJob)
        .where(
            PublishJob.user_id == user_id,
            PublishJob.task_id == task_id,
            PublishJob.video_key == video_key,
            PublishJob.render_version_id == "",
        )
        .values(
            render_version_id=render_version_id,
            render_version=render_version,
        )
        .execution_options(synchronize_session=False)
    )


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


async def claim_job(db: AsyncSession, job_id: str) -> PublishJob | None:
    result = await db.execute(
        update(PublishJob)
        .where(PublishJob.id == job_id, PublishJob.status == "queued")
        .values(status="publishing", queue_message_id="")
        .execution_options(synchronize_session=False)
    )
    if int(getattr(result, "rowcount", 0) or 0) != 1:
        await db.rollback()
        return None
    await db.commit()
    return await get_job(db, job_id)


async def record_queue_message(db: AsyncSession, job_id: str, message_id: str) -> None:
    await db.execute(
        update(PublishJob)
        .where(
            PublishJob.id == job_id,
            PublishJob.status == "queued",
            PublishJob.queue_message_id == "",
        )
        .values(queue_message_id=message_id)
        .execution_options(synchronize_session=False)
    )
    await db.commit()


async def list_jobs(
    db: AsyncSession,
    user_id: str,
    status: str | None,
    page: int,
    page_size: int,
    task_id: str = "",
) -> tuple[list[PublishJob], int]:
    cond = PublishJob.user_id == user_id
    if status:
        cond = cond & (PublishJob.status == status)
    if task_id:
        cond = cond & (PublishJob.task_id == task_id)
    total = (await db.execute(select(func.count(PublishJob.id)).where(cond))).scalar() or 0
    res = await db.execute(
        select(PublishJob)
        .where(cond)
        .order_by(PublishJob.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(res.scalars().all()), int(total)


async def list_recoverable_jobs(
    db: AsyncSession,
    *,
    publishing_stale_before: datetime,
) -> list[PublishJob]:
    result = await db.execute(
        select(PublishJob).where(
            ((PublishJob.status == "publishing") & (PublishJob.updated_at < publishing_stale_before))
            | ((PublishJob.status == "queued") & (PublishJob.queue_message_id == ""))
        )
    )
    return list(result.scalars().all())
