"""publish 业务编排（F-501~F-504）
- 扫码授权：driver.qrcode_login → 前端轮询 check_login → 会话落库
- 发布执行：queued → (定时到点) publishing → success/failed
- 失败降级：重试 / 仅导出 MP4；登录态失效红色告警
- 日志：发布失败/账号过期（§10.6.8-A #5）
"""

import json
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.events import CHANNEL_FEED, CHANNEL_TASKS
from app.core.events import publish as emit
from app.core.logging import get_logger
from app.core.storage import read_bytes, save_bytes
from app.modules.notify.service import notify_user
from app.providers.registry import registry

from . import repository as repo
from .models import PLATFORM_NAMES, PublishAccount, PublishJob
from .schemas import (
    AccountOut,
    ExportOut,
    JobOut,
    JobPageOut,
    PublishCapabilityOut,
    PublishIn,
    QrcodePollOut,
    QrcodeStartOut,
)

logger = get_logger("oral.publish")
settings = get_settings()

_PLATFORM_MODES = {
    "douyin": "automatic",
    "xiaohongshu": "semi_automatic",
    "shipinhao": "semi_automatic",
}


def account_to_out(a: PublishAccount) -> AccountOut:
    return AccountOut(
        id=a.id,
        platform=a.platform,
        platformName=PLATFORM_NAMES.get(a.platform, a.platform),
        nickname=a.nickname,
        status=a.status,
        createdAt=a.created_at.astimezone(UTC).isoformat(),
    )


def job_to_out(j: PublishJob, account: PublishAccount | None = None) -> JobOut:
    return JobOut(
        id=j.id,
        taskId=j.task_id,
        platform=j.platform,
        platformName=PLATFORM_NAMES.get(j.platform, j.platform),
        accountId=j.account_id,
        accountNickname=account.nickname if account else "",
        title=j.title,
        status=j.status,
        scheduledAt=j.scheduled_at or None,
        error=j.error,
        postId=j.post_id,
        videoUrl=f"/media/{j.video_key}" if j.video_key else None,
        packageUrl=f"/media/{j.export_key}" if j.export_key else None,
        retryCount=int(j.retry_count or "0"),
        createdAt=j.created_at.astimezone(UTC).isoformat(),
        updatedAt=j.updated_at.astimezone(UTC).isoformat(),
    )


def publish_capabilities() -> list[PublishCapabilityOut]:
    verified = {item.strip() for item in settings.publish_verified_platforms.split(",") if item.strip()}
    capabilities: list[PublishCapabilityOut] = []
    for platform, platform_name in PLATFORM_NAMES.items():
        if settings.app_env == "dev":
            capabilities.append(
                PublishCapabilityOut(
                    platform=platform,
                    platformName=platform_name,
                    mode="development_mock",
                    verificationStatus="development_mock",
                    automaticEnabled=True,
                    reason="开发环境模拟发布，结果不代表真实平台可用性",
                )
            )
        elif platform in verified:
            capabilities.append(
                PublishCapabilityOut(
                    platform=platform,
                    platformName=platform_name,
                    mode=_PLATFORM_MODES[platform],
                    verificationStatus="verified",
                    automaticEnabled=True,
                    reason="已通过真实账号发布验收",
                )
            )
        else:
            capabilities.append(
                PublishCapabilityOut(
                    platform=platform,
                    platformName=platform_name,
                    mode="export_only",
                    verificationStatus="unverified",
                    automaticEnabled=False,
                    reason="尚未完成真实账号验收，仅提供完整人工发布包",
                )
            )
    return capabilities


def _capability(platform: str) -> PublishCapabilityOut:
    return next(item for item in publish_capabilities() if item.platform == platform)


# ============ 账号授权（F-501/502） ============


async def list_accounts(db: AsyncSession, user_id: str) -> list[AccountOut]:
    return [account_to_out(a) for a in await repo.list_accounts(db, user_id)]


async def qrcode_start(platform: str) -> QrcodeStartOut:
    _check_platform(platform)
    if not _capability(platform).automaticEnabled:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "AUTOMATION_NOT_VERIFIED",
                "message": f"{PLATFORM_NAMES[platform]}自动发布尚未完成真实验收，请使用人工发布包",
            },
        )
    driver = registry.publish_driver(platform)
    data = await driver.qrcode_login()
    return QrcodeStartOut(ticket=data["ticket"], qrcodeUrl=data["qrcodeUrl"])


async def qrcode_poll(db: AsyncSession, user_id: str, platform: str, ticket: str) -> QrcodePollOut:
    _check_platform(platform)
    if not _capability(platform).automaticEnabled:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "AUTOMATION_NOT_VERIFIED", "message": "该平台自动发布尚未完成真实验收"},
        )
    driver = registry.publish_driver(platform)
    session = await driver.check_login(ticket)
    if session is None:
        return QrcodePollOut(status="waiting")
    # 等待扫码中：透传最新二维码（平台二维码过期刷新后前端同步换图）
    if session.get("_waiting"):
        return QrcodePollOut(status="waiting", qrcodeUrl=session.get("qrcode_url") or None)
    # 登录失败：返回 expired 状态告知前端
    if session.get("_failed"):
        return QrcodePollOut(status="expired")
    account = await repo.create_account(
        db,
        user_id=user_id,
        platform=platform,
        nickname=session.get("nickname", f"{PLATFORM_NAMES[platform]} 账号"),
        session_json=json.dumps(session, ensure_ascii=False),
        status="active",
    )
    await emit(
        CHANNEL_FEED,
        {
            "kind": "feed",
            "userId": user_id,
            "event": {
                "id": account.id[:12],
                "type": "ok",
                "text": f"{PLATFORM_NAMES[platform]} 账号「{account.nickname}」授权成功",
                "createdAt": datetime.now(UTC).isoformat(),
            },
        },
    )
    return QrcodePollOut(status="success", account=account_to_out(account))


async def remove_account(db: AsyncSession, user_id: str, account_id: str) -> None:
    a = await repo.get_account(db, account_id, user_id)
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "账号不存在"})
    await repo.delete_account(db, a)


async def rename_account(db: AsyncSession, user_id: str, account_id: str, nickname: str) -> AccountOut:
    """账号重命名（多账号辨识）：昵称提取失败或与平台同名时，用户可手动标记"""
    a = await repo.get_account(db, account_id, user_id)
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "账号不存在"})
    cleaned = nickname.strip()[:30]
    if not cleaned:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "NICKNAME_EMPTY", "message": "账号名称不能为空"}
        )
    a.nickname = cleaned
    await repo.save_account(db, a)
    logger.info("account_renamed", account_id=account_id, nickname=cleaned)
    return account_to_out(a)


async def reauth_account(db: AsyncSession, user_id: str, account_id: str) -> QrcodeStartOut:
    """登录态失效 → 一键重新授权（发起新扫码）"""
    a = await repo.get_account(db, account_id, user_id)
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "账号不存在"})
    return await qrcode_start(a.platform)


# ============ 发布任务（F-503/504） ============


async def publish_task_video(
    db: AsyncSession,
    user_id: str,
    task_id: str,
    platforms: list[str],
    title: str,
    video_key: str,
    cover_key: str | None,
    scheduled_at: str | None = None,
    topics: list[str] | None = None,
) -> list[str]:
    """供 pipeline engine step_publish 调用：为各平台建发布任务并调度执行"""
    job_ids: list[str] = []
    for platform in platforms:
        _check_platform(platform)
        topics_json = json.dumps(topics or [], ensure_ascii=False)
        existing = await repo.get_task_platform_job(db, user_id, task_id, platform)
        if existing is not None and _can_reuse_publish_job(
            existing,
            title=title,
            video_key=video_key,
            cover_key=cover_key or "",
            scheduled_at=scheduled_at or "",
            topics_json=topics_json,
        ):
            job_ids.append(existing.id)
            continue
        capability = _capability(platform)
        if not capability.automaticEnabled:
            job = await repo.create_job(
                db,
                user_id=user_id,
                task_id=task_id,
                platform=platform,
                title=title,
                topics_json=topics_json,
                video_key=video_key,
                cover_key=cover_key or "",
                scheduled_at=scheduled_at or "",
                status="export_ready",
                error=capability.reason,
            )
            await notify_user(
                db,
                user_id,
                "warn",
                f"{PLATFORM_NAMES[platform]}任务等待人工发布",
                "自动发布尚未完成真实验收，可在发布任务中下载完整发布包。",
            )
            job_ids.append(job.id)
            continue
        account = await repo.active_account_for(db, user_id, platform)
        if account is None:
            job = await repo.create_job(
                db,
                user_id=user_id,
                task_id=task_id,
                platform=platform,
                title=title,
                video_key=video_key,
                cover_key=cover_key or "",
                topics_json=topics_json,
                status="failed",
                error=f"未授权{PLATFORM_NAMES[platform]}账号，请到「发布-账号」扫码授权",
            )
            await notify_user(
                db,
                user_id,
                "error",
                f"{PLATFORM_NAMES[platform]}发布失败：未授权账号",
                "请到「发布-账号」扫码授权，或下载完整人工发布包。",
            )
            job_ids.append(job.id)
            continue
        job = await repo.create_job(
            db,
            user_id=user_id,
            task_id=task_id,
            account_id=account.id,
            platform=platform,
            title=title,
            video_key=video_key,
            cover_key=cover_key or "",
            topics_json=topics_json,
            scheduled_at=scheduled_at or "",
        )
        job_ids.append(job.id)
        await _enqueue_job(db, job)
    return job_ids


async def create_jobs(db: AsyncSession, user_id: str, inp: PublishIn) -> list[JobOut]:
    """手动创建发布任务（发布管理页）"""
    if not inp.platforms:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "PLATFORM_REQUIRED", "message": "至少选择一个平台"}
        )
    ids = await publish_task_video(
        db,
        user_id,
        inp.taskId or "",
        inp.platforms,
        inp.title,
        inp.videoKey,
        inp.coverKey,
        inp.publishAt,
        inp.topics,
    )
    jobs = []
    for jid in ids:
        j = await repo.get_job(db, jid, user_id)
        acc = await repo.get_account(db, j.account_id, user_id) if j and j.account_id else None
        if j:
            jobs.append(job_to_out(j, acc))
    return jobs


async def list_jobs(db: AsyncSession, user_id: str, status_: str | None, page: int, page_size: int) -> JobPageOut:
    items, total = await repo.list_jobs(db, user_id, status_, page, page_size)
    outs = []
    for j in items:
        acc = await repo.get_account(db, j.account_id, user_id) if j.account_id else None
        outs.append(job_to_out(j, acc))
    return JobPageOut(items=outs, total=total, page=page, pageSize=page_size)


async def retry_job(db: AsyncSession, user_id: str, job_id: str) -> JobOut:
    j = await _must_job(db, job_id, user_id)
    if j.status not in ("failed",):
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "NOT_FAILED", "message": "仅失败任务可重试"})
    account = await repo.get_account(db, j.account_id, user_id) if j.account_id else None
    if account is None or account.status != "active":
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail={"code": "ACCOUNT_EXPIRED", "message": "账号登录态失效，请重新授权"}
        )
    j.status = "queued"
    j.error = ""
    j.retry_count = str(int(j.retry_count or "0") + 1)
    await _enqueue_job(db, j)
    return job_to_out(j, account)


async def export_job(db: AsyncSession, user_id: str, job_id: str) -> ExportOut:
    """生成视频、封面和元数据齐全的人工发布 ZIP 包。"""
    j = await _must_job(db, job_id, user_id)
    if not j.video_key:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "NO_VIDEO", "message": "该任务无成片可导出"}
        )
    video_name = f"video{Path(j.video_key).suffix or '.mp4'}"
    cover_name = f"cover{Path(j.cover_key).suffix or '.jpg'}" if j.cover_key else ""
    metadata: dict[str, object] = {
        "jobId": j.id,
        "taskId": j.task_id,
        "platform": j.platform,
        "platformName": PLATFORM_NAMES.get(j.platform, j.platform),
        "title": j.title,
        "topics": json.loads(j.topics_json or "[]"),
        "scheduledAt": j.scheduled_at or None,
        "videoFilename": video_name,
        "coverFilename": cover_name or None,
        "createdAt": j.created_at.astimezone(UTC).isoformat(),
    }
    try:
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(video_name, await read_bytes(j.video_key))
            if j.cover_key:
                archive.writestr(cover_name, await read_bytes(j.cover_key))
            archive.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
        j.export_key = await save_bytes("publish-packages", f"{j.id}.zip", buffer.getvalue())
    except Exception as exc:  # noqa: BLE001
        logger.exception("publish_package_failed", job_id=j.id, user_id=user_id)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "EXPORT_PACKAGE_FAILED", "message": "发布包生成失败，请稍后重试"},
        ) from exc
    if j.status != "success":
        j.status = "export_ready"
    await repo.save_job(db, j)
    return ExportOut(
        jobId=j.id,
        videoUrl=f"/media/{j.video_key}",
        packageKey=j.export_key,
        packageUrl=f"/media/{j.export_key}",
        metadata=metadata,
    )


# ============ 发布执行器（Dramatiq 持久延时任务） ============


def _schedule_job(job_id: str, scheduled_at: str = "") -> str:
    from app.workers.tasks import run_publish_job

    delay_ms = 0
    if scheduled_at:
        try:
            target = datetime.fromisoformat(scheduled_at)
            if target.tzinfo is None:
                target = target.replace(tzinfo=UTC)
            delay_ms = max(0, int((target - datetime.now(UTC)).total_seconds() * 1000))
        except ValueError:
            delay_ms = 0
    message = run_publish_job.send_with_options(args=(job_id,), delay=delay_ms or None)
    return message.message_id


async def _run_job(job_id: str) -> None:
    async with SessionLocal() as db:
        job = await repo.claim_job(db, job_id)
        if job is None:
            return
        # 时钟偏差或提前投递时重新安排，不在 Worker 内 sleep 占槽位。
        if job.scheduled_at:
            try:
                target = datetime.fromisoformat(job.scheduled_at)
                if target.tzinfo is None:
                    target = target.replace(tzinfo=UTC)
                if target > datetime.now(UTC):
                    job.status = "queued"
                    await _enqueue_job(db, job)
                    return
            except ValueError:
                pass
        account = await repo.get_account(db, job.account_id, job.user_id)
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
            await write_audit(
                "account_expired",
                user_id=job.user_id,
                detail=f"platform={job.platform},account_id={job.account_id},job_id={job.id}",
            )
            await notify_user(
                db,
                job.user_id,
                "error",
                f"{PLATFORM_NAMES.get(job.platform)}登录态失效",
                "发布任务已停止，不会自动重试；请重新授权或导出人工发布包。",
            )
            return
        await emit(
            CHANNEL_TASKS, {"kind": "publish_updated", "jobId": job.id, "userId": job.user_id, "status": "publishing"}
        )
        try:
            driver = registry.publish_driver(job.platform)
            session = repo.account_session(account)
            post_id = await driver.publish(
                session,
                job.video_key,
                job.title,
                json.loads(job.topics_json or "[]"),
                job.cover_key or None,
                scheduled_at=job.scheduled_at or None,
                account_id=account.id,
            )
            # SAU 发布过程中可能刷新 Cookie，回写 DB
            if session:
                account.session_json = json.dumps(session, ensure_ascii=False)
                await repo.save_account(db, account)
            job.status = "success"
            job.post_id = post_id
            await repo.save_job(db, job)
            # 发布成功日志（§10.6.8-B #7）
            logger.info(
                "publish_success",
                job_id=job.id,
                user_id=job.user_id,
                platform=job.platform,
                post_id=post_id,
            )
            await emit(
                CHANNEL_TASKS, {"kind": "publish_updated", "jobId": job.id, "userId": job.user_id, "status": "success"}
            )
            await notify_user(
                db,
                job.user_id,
                "info",
                f"{PLATFORM_NAMES.get(job.platform)}发布成功",
                f"「{job.title[:40]}」已完成发布。",
            )
            await emit(
                CHANNEL_FEED,
                {
                    "kind": "feed",
                    "userId": job.user_id,
                    "event": {
                        "id": job.id[:12],
                        "type": "ok",
                        "text": f"「{job.title[:18]}」已发布到{PLATFORM_NAMES.get(job.platform)}",
                        "createdAt": datetime.now(UTC).isoformat(),
                    },
                },
            )
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
            await write_audit(
                "publish_failed",
                user_id=job.user_id,
                detail=f"job_id={job_id},platform={job.platform},error={str(e)[:200]}",
            )
            job.status = "failed"
            job.error = str(e)[:300]
            await repo.save_job(db, job)
            await notify_user(
                db,
                job.user_id,
                "error",
                f"{PLATFORM_NAMES.get(job.platform)}发布失败",
                f"{str(e)[:160]}。可重试或导出完整人工发布包。",
            )
            await emit(
                CHANNEL_TASKS, {"kind": "publish_updated", "jobId": job.id, "userId": job.user_id, "status": "failed"}
            )


async def recover_publish_jobs(db: AsyncSession) -> int:
    """重启后恢复未入队发布；结果未知的 publishing 任务转人工导出。"""
    jobs = await repo.list_recoverable_jobs(db)
    recovered = 0
    unknown_jobs: list[PublishJob] = []
    for job in jobs:
        if job.status == "publishing":
            job.status = "failed"
            job.error = "服务重启时发布结果未知，为避免重复发布已停止自动重试，请导出后人工核对"
            job.queue_message_id = ""
            unknown_jobs.append(job)
            continue
        job.queue_message_id = ""
        recovered += 1
    if jobs:
        await db.commit()
    for job in unknown_jobs:
        await notify_user(
            db,
            job.user_id,
            "error",
            f"{PLATFORM_NAMES.get(job.platform)}发布结果需要人工核对",
            "服务重启时平台结果未知，为避免重复发布已停止自动重试；请先到平台核对，再导出人工发布包。",
        )
    for job in jobs:
        if job.status == "queued":
            await _enqueue_job(db, job)
    if jobs:
        logger.warning("publish_jobs_recovered", queued=recovered, unknown=len(jobs) - recovered)
    return recovered


async def _enqueue_job(db: AsyncSession, job: PublishJob) -> None:
    """先持久化可恢复状态，再投递 Broker，最后条件回写消息号。"""
    job.status = "queued"
    job.queue_message_id = ""
    await repo.save_job(db, job)
    message_id = _schedule_job(job.id, job.scheduled_at)
    await repo.record_queue_message(db, job.id, message_id)
    await db.refresh(job)


def _can_reuse_publish_job(
    job: PublishJob,
    *,
    title: str,
    video_key: str,
    cover_key: str,
    scheduled_at: str,
    topics_json: str,
) -> bool:
    same_payload = (
        job.title == title
        and job.video_key == video_key
        and job.cover_key == cover_key
        and job.scheduled_at == scheduled_at
        and job.topics_json == topics_json
    )
    if not same_payload:
        return False
    if job.status in {"queued", "publishing", "success", "export_ready"}:
        return True
    return job.status == "failed" and "发布结果未知" in job.error


def _check_platform(platform: str) -> None:
    if platform not in PLATFORM_NAMES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "BAD_PLATFORM", "message": f"不支持的平台：{platform}"},
        )


async def _must_job(db: AsyncSession, job_id: str, user_id: str) -> PublishJob:
    j = await repo.get_job(db, job_id, user_id)
    if j is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "发布任务不存在"})
    return j
