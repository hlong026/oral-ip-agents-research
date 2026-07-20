"""publish 业务编排（F-501~F-504）
- 扫码授权：driver.qrcode_login → 前端轮询 check_login → 会话落库
- 发布执行：queued → (定时到点) publishing → success/failed
- 失败降级：重试 / 仅导出 MP4；登录态失效红色告警
- 日志：发布失败/账号过期（§10.6.8-A #5）
"""
import asyncio
import json
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.core.events import CHANNEL_ALERT, CHANNEL_FEED, CHANNEL_TASKS
from app.core.events import publish as emit
from app.core.logging import get_logger
from app.providers.registry import registry

from . import repository as repo
from .models import PLATFORM_NAMES, PublishAccount, PublishJob
from .schemas import AccountOut, ExportOut, JobOut, JobPageOut, PublishIn, QrcodePollOut, QrcodeStartOut

logger = get_logger("oral.publish")


def account_to_out(a: PublishAccount) -> AccountOut:
    return AccountOut(
        id=a.id, platform=a.platform, platformName=PLATFORM_NAMES.get(a.platform, a.platform),
        nickname=a.nickname, status=a.status,
        createdAt=a.created_at.astimezone(UTC).isoformat())


def job_to_out(j: PublishJob, account: PublishAccount | None = None) -> JobOut:
    return JobOut(
        id=j.id, taskId=j.task_id, platform=j.platform,
        platformName=PLATFORM_NAMES.get(j.platform, j.platform),
        accountId=j.account_id, accountNickname=account.nickname if account else "",
        title=j.title, status=j.status, scheduledAt=j.scheduled_at or None,
        error=j.error, postId=j.post_id,
        videoUrl=f"/media/{j.video_key}" if j.video_key else None,
        retryCount=int(j.retry_count or "0"),
        createdAt=j.created_at.astimezone(UTC).isoformat(),
        updatedAt=j.updated_at.astimezone(UTC).isoformat())


# ============ 账号授权（F-501/502） ============

async def list_accounts(db: AsyncSession, user_id: str) -> list[AccountOut]:
    return [account_to_out(a) for a in await repo.list_accounts(db, user_id)]


async def qrcode_start(platform: str) -> QrcodeStartOut:
    _check_platform(platform)
    driver = registry.publish_driver(platform)
    data = await driver.qrcode_login()
    return QrcodeStartOut(ticket=data["ticket"], qrcodeUrl=data["qrcodeUrl"])


async def qrcode_poll(db: AsyncSession, user_id: str, platform: str, ticket: str) -> QrcodePollOut:
    _check_platform(platform)
    driver = registry.publish_driver(platform)
    session = await driver.check_login(ticket)
    if session is None:
        return QrcodePollOut(status="waiting")
    account = await repo.create_account(
        db, user_id=user_id, platform=platform,
        nickname=session.get("nickname", f"{PLATFORM_NAMES[platform]} 账号"),
        session_json=json.dumps(session, ensure_ascii=False), status="active")
    await emit(CHANNEL_FEED, {"kind": "feed", "userId": user_id, "event": {
        "id": account.id[:12], "type": "ok",
        "text": f"{PLATFORM_NAMES[platform]} 账号「{account.nickname}」授权成功",
        "createdAt": datetime.now(UTC).isoformat()}})
    return QrcodePollOut(status="success", account=account_to_out(account))


async def remove_account(db: AsyncSession, user_id: str, account_id: str) -> None:
    a = await repo.get_account(db, account_id, user_id)
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "账号不存在"})
    await repo.delete_account(db, a)


async def reauth_account(db: AsyncSession, user_id: str, account_id: str) -> QrcodeStartOut:
    """登录态失效 → 一键重新授权（发起新扫码）"""
    a = await repo.get_account(db, account_id, user_id)
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "账号不存在"})
    return await qrcode_start(a.platform)


# ============ 发布任务（F-503/504） ============

async def publish_task_video(db: AsyncSession, user_id: str, task_id: str, platforms: list[str],
                             title: str, video_key: str, cover_key: str | None,
                             scheduled_at: str | None = None) -> list[str]:
    """供 pipeline engine step_publish 调用：为各平台建发布任务并调度执行"""
    job_ids: list[str] = []
    for platform in platforms:
        _check_platform(platform)
        account = await repo.active_account_for(db, user_id, platform)
        if account is None:
            job = await repo.create_job(
                db, user_id=user_id, task_id=task_id, platform=platform, title=title,
                video_key=video_key, cover_key=cover_key or "", status="failed",
                error=f"未授权{PLATFORM_NAMES[platform]}账号，请到「发布-账号」扫码授权")
            await emit(CHANNEL_ALERT, {"level": "error", "userId": user_id,
                                       "message": f"{PLATFORM_NAMES[platform]}发布失败：未授权账号",
                                       "jobId": job.id})
            job_ids.append(job.id)
            continue
        job = await repo.create_job(
            db, user_id=user_id, task_id=task_id, account_id=account.id, platform=platform,
            title=title, video_key=video_key, cover_key=cover_key or "",
            scheduled_at=scheduled_at or "")
        job_ids.append(job.id)
        _schedule_job(job.id)
    return job_ids


async def create_jobs(db: AsyncSession, user_id: str, inp: PublishIn) -> list[JobOut]:
    """手动创建发布任务（发布管理页）"""
    if not inp.platforms:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail={"code": "PLATFORM_REQUIRED", "message": "至少选择一个平台"})
    ids = await publish_task_video(db, user_id, inp.taskId or "", inp.platforms, inp.title,
                                   inp.videoKey, inp.coverKey, inp.publishAt)
    jobs = []
    for jid in ids:
        j = await repo.get_job(db, jid, user_id)
        acc = await repo.get_account(db, j.account_id) if j and j.account_id else None
        if j:
            jobs.append(job_to_out(j, acc))
    return jobs


async def list_jobs(db: AsyncSession, user_id: str, status_: str | None,
                    page: int, page_size: int) -> JobPageOut:
    items, total = await repo.list_jobs(db, user_id, status_, page, page_size)
    outs = []
    for j in items:
        acc = await repo.get_account(db, j.account_id) if j.account_id else None
        outs.append(job_to_out(j, acc))
    return JobPageOut(items=outs, total=total, page=page, pageSize=page_size)


async def retry_job(db: AsyncSession, user_id: str, job_id: str) -> JobOut:
    j = await _must_job(db, job_id, user_id)
    if j.status not in ("failed",):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"code": "NOT_FAILED", "message": "仅失败任务可重试"})
    account = await repo.get_account(db, j.account_id) if j.account_id else None
    if account is None or account.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"code": "ACCOUNT_EXPIRED", "message": "账号登录态失效，请重新授权"})
    j.status = "queued"
    j.error = ""
    j.retry_count = str(int(j.retry_count or "0") + 1)
    await repo.save_job(db, j)
    _schedule_job(j.id)
    return job_to_out(j, account)


async def export_job(db: AsyncSession, user_id: str, job_id: str) -> ExportOut:
    """发布失败降级：仅导出 MP4（F-504）"""
    j = await _must_job(db, job_id, user_id)
    if not j.video_key:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail={"code": "NO_VIDEO", "message": "该任务无成片可导出"})
    return ExportOut(jobId=j.id, videoUrl=f"/media/{j.video_key}")


# ============ 发布执行器（进程内调度；生产由 Dramatiq 定时器接管） ============

def _schedule_job(job_id: str) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()
    loop.create_task(_run_job(job_id))


async def _run_job(job_id: str) -> None:
    async with SessionLocal() as db:
        job = await repo.get_job(db, job_id)
        if job is None or job.status != "queued":
            return
        # 定时发布：到点前等待（MVP 进程内 sleep；生产用 Dramatiq 定时器，重启不丢）
        if job.scheduled_at:
            try:
                delay = (datetime.fromisoformat(job.scheduled_at) - datetime.now(UTC)).total_seconds()
                if delay > 0:
                    await asyncio.sleep(min(delay, 86400 * 7))
            except ValueError:
                pass
        account = await repo.get_account(db, job.account_id)
        if account is None or account.status != "active":
            job.status = "failed"
            job.error = "账号登录态失效，请重新授权"
            await repo.save_job(db, job)
            # 账号过期：记录 WARNING（§10.6.8-A #5）
            logger.warning(
                "account_expired",
                user_id=job.user_id,
                platform=job.platform,
                account_id=job.account_id,
                job_id=job.id,
            )
            await emit(CHANNEL_ALERT, {"level": "error", "userId": job.user_id,
                                       "message": f"{PLATFORM_NAMES.get(job.platform)}登录态失效", "jobId": job.id})
            return
        job.status = "publishing"
        await repo.save_job(db, job)
        await emit(CHANNEL_TASKS, {"kind": "publish_updated", "jobId": job.id,
                                   "userId": job.user_id, "status": "publishing"})
        try:
            driver = registry.publish_driver(job.platform)
            session = json.loads(account.session_json or "{}")
            post_id = await driver.publish(session, job.video_key, job.title,
                                           json.loads(job.topics_json or "[]"), job.cover_key or None)
            job.status = "success"
            job.post_id = post_id
            await repo.save_job(db, job)
            await emit(CHANNEL_TASKS, {"kind": "publish_updated", "jobId": job.id,
                                       "userId": job.user_id, "status": "success"})
            await emit(CHANNEL_FEED, {"kind": "feed", "userId": job.user_id, "event": {
                "id": job.id[:12], "type": "ok",
                "text": f"「{job.title[:18]}」已发布到{PLATFORM_NAMES.get(job.platform)}",
                "createdAt": datetime.now(UTC).isoformat()}})
        except Exception as e:  # noqa: BLE001
            # 发布失败：记录 ERROR（§10.6.8-A #5）
            logger.error(
                "publish_failed",
                job_id=job_id,
                user_id=job.user_id,
                platform=job.platform,
                error=str(e)[:200],
                retry_count=job.retry_count,
            )
            job.status = "failed"
            job.error = str(e)[:300]
            await repo.save_job(db, job)
            await emit(CHANNEL_ALERT, {"level": "error", "userId": job.user_id,
                                       "message": f"{PLATFORM_NAMES.get(job.platform)}发布失败：{str(e)[:60]}",
                                       "jobId": job.id})
            await emit(CHANNEL_TASKS, {"kind": "publish_updated", "jobId": job.id,
                                       "userId": job.user_id, "status": "failed"})


def _check_platform(platform: str) -> None:
    if platform not in PLATFORM_NAMES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail={"code": "BAD_PLATFORM", "message": f"不支持的平台：{platform}"})


async def _must_job(db: AsyncSession, job_id: str, user_id: str) -> PublishJob:
    j = await repo.get_job(db, job_id, user_id)
    if j is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail={"code": "NOT_FOUND", "message": "发布任务不存在"})
    return j
