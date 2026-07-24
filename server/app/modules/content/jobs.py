"""文案长耗时操作的持久后台任务。"""

import json
import math
from datetime import UTC
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.core.events import CHANNEL_TASKS, publish
from app.core.logging import get_logger
from app.core.storage import read_bytes, save_bytes
from app.core.white_label import public_error_message, public_metadata
from app.modules.billing.service import (
    attach_reservation,
    quote_operation_unit,
    recover_reservation_after_failure,
    release_reservation,
    reserve_metered_operation,
    settle_reservation,
)
from app.providers.base import ProviderError
from app.providers.duration_probe import probe_media_bytes

from . import repository
from . import service as content_service
from .models import ContentJob
from .schemas import ContentJobOut

logger = get_logger("oral.content.jobs")


def schedule_content_job(job_id: str) -> str:
    from app.workers.tasks import run_content_job

    return run_content_job.send(job_id).message_id


async def submit_rewrite(
    db: AsyncSession,
    *,
    user_id: str,
    text: str,
    intensity: str,
    prompt: str | None,
    script_id: str | None,
    quote_id: str | None,
) -> ContentJobOut:
    characters = max(1, len(text + (prompt or "")))
    reservation_id = await reserve_metered_operation(
        db,
        user_id,
        quote_id,
        "script_generation",
        {"characters": characters, "tokens": max(1, (characters + 1) // 2), "assets": 1},
    )
    return await _create_and_schedule(
        db,
        user_id=user_id,
        kind="rewrite",
        reservation_id=reservation_id,
        payload={
            "text": text,
            "intensity": intensity,
            "prompt": prompt,
            "scriptId": script_id,
        },
    )


async def submit_similarity(
    db: AsyncSession,
    *,
    user_id: str,
    text: str,
    quote_id: str | None,
) -> ContentJobOut:
    characters = max(1, len(text))
    reservation_id = await reserve_metered_operation(
        db,
        user_id,
        quote_id,
        "script_generation",
        {"characters": characters, "tokens": max(1, (characters + 1) // 2), "assets": 1},
    )
    return await _create_and_schedule(
        db,
        user_id=user_id,
        kind="similarity",
        reservation_id=reservation_id,
        payload={"text": text},
    )


async def submit_parse_url(
    db: AsyncSession,
    *,
    user_id: str,
    persona_id: str | None,
    url: str,
    quote_id: str | None,
) -> ContentJobOut:
    unit = await quote_operation_unit(db, user_id, quote_id, "asr")
    duration = await content_service.probe_url_duration(
        url,
        required=unit in {"per_minute", "per_second"},
    )
    seconds = max(1, math.ceil(duration or 1))
    reservation_id = await reserve_metered_operation(
        db,
        user_id,
        quote_id,
        "asr",
        {"seconds": seconds, "assets": 1},
    )
    return await _create_and_schedule(
        db,
        user_id=user_id,
        kind="parse_url",
        reservation_id=reservation_id,
        payload={
            "url": url,
            "personaId": persona_id,
            "verifiedDurationSeconds": duration,
        },
    )


async def submit_parse_upload(
    db: AsyncSession,
    *,
    user_id: str,
    persona_id: str | None,
    filename: str,
    data: bytes,
    quote_id: str | None,
) -> ContentJobOut:
    unit = await quote_operation_unit(db, user_id, quote_id, "asr")
    duration = await probe_media_bytes(data, Path(filename).suffix)
    if unit in {"per_minute", "per_second"} and duration is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "MEDIA_DURATION_UNVERIFIED", "message": "无法验证媒体时长，暂不能执行转写"},
        )
    seconds = max(1, math.ceil(duration or 1))
    reservation_id = await reserve_metered_operation(
        db,
        user_id,
        quote_id,
        "asr",
        {"seconds": seconds, "assets": 1},
    )
    storage_key = await save_bytes("content-jobs", filename, data)
    return await _create_and_schedule(
        db,
        user_id=user_id,
        kind="parse_upload",
        reservation_id=reservation_id,
        payload={
            "filename": filename,
            "storageKey": storage_key,
            "personaId": persona_id,
            "durationSeconds": duration,
        },
    )


async def get_job(db: AsyncSession, user_id: str, job_id: str) -> ContentJobOut:
    job = await repository.get_job(db, job_id, user_id)
    if job is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "CONTENT_JOB_NOT_FOUND", "message": "文案任务不存在"},
        )
    return to_out(job)


async def _create_and_schedule(
    db: AsyncSession,
    *,
    user_id: str,
    kind: str,
    reservation_id: str,
    payload: dict,
) -> ContentJobOut:
    try:
        job = await repository.create_job(
            db,
            user_id=user_id,
            kind=kind,
            payload_json=json.dumps(payload, ensure_ascii=False),
            reservation_id=reservation_id,
        )
        await attach_reservation(db, reservation_id, user_id, job.id)
        await db.commit()
    except BaseException:
        await db.rollback()
        await recover_reservation_after_failure(db, reservation_id, user_id)
        raise

    try:
        message_id = schedule_content_job(job.id)
        await repository.record_job_message(db, job.id, message_id)
        await db.refresh(job)
    except BaseException as exc:
        logger.exception("content_job_enqueue_failed", job_id=job.id, kind=kind)
        job.status = "failed"
        job.error = "后台任务暂时不可用，请稍后重试"
        await db.commit()
        await release_reservation(db, reservation_id, user_id)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "CONTENT_JOB_ENQUEUE_FAILED", "message": "后台任务暂时不可用，请稍后重试"},
        ) from exc
    return to_out(job)


async def run_content_job(job_id: str) -> None:
    async with SessionLocal() as db:
        job = await repository.claim_job(db, job_id)
        if job is None:
            return
        await _emit(job)
        result_persisted = False
        try:
            result = await _execute(db, job)
            job.result_json = json.dumps(result, ensure_ascii=False)
            job.progress = 95
            job.stage = "正在结算积分"
            await db.commit()
            result_persisted = True
            await _emit(job)

            settled = await settle_reservation(
                db,
                job.reservation_id,
                job.id,
                step=_billing_step(job.kind),
            )
            if settled <= 0:
                raise RuntimeError("积分结算失败")

            job.status = "done"
            job.progress = 100
            job.stage = "处理完成"
            await db.commit()
            await _emit(job)
            logger.info("content_job_done", job_id=job.id, user_id=job.user_id, kind=job.kind)
        except BaseException as exc:
            await db.rollback()
            current = await repository.get_job(db, job_id)
            if current is None:
                return
            current.status = "failed"
            current.stage = "处理失败"
            current.error = _error_message(exc)
            await db.commit()
            if result_persisted:
                await recover_reservation_after_failure(
                    db,
                    current.reservation_id,
                    current.user_id,
                )
            else:
                await release_reservation(db, current.reservation_id, current.user_id)
            await _emit(current)
            logger.exception(
                "content_job_failed",
                job_id=current.id,
                user_id=current.user_id,
                kind=current.kind,
                error=current.error[:200],
            )


async def _execute(db: AsyncSession, job: ContentJob) -> dict:
    payload = json.loads(job.payload_json or "{}")

    async def progress(value: int, stage: str) -> None:
        await _update_progress(job.id, value, stage)

    if job.kind == "parse_url":
        await progress(25, "正在解析视频并提取音频")
        parse_result = await content_service.parse_url(
            db,
            job.user_id,
            str(payload["url"]),
            payload.get("personaId"),
            payload.get("verifiedDurationSeconds"),
        )
        return parse_result.model_dump()
    if job.kind == "parse_upload":
        await progress(25, "正在读取上传媒体")
        storage_key = str(payload["storageKey"])
        data = await read_bytes(storage_key)
        await progress(45, "正在提取音轨并转写文案")
        upload_result = await content_service.parse_upload(
            db,
            job.user_id,
            str(payload["filename"]),
            data,
            payload.get("personaId"),
            payload.get("durationSeconds"),
            storage_key=storage_key,
        )
        return upload_result.model_dump()
    if job.kind == "rewrite":
        rewrite_result = await content_service.rewrite(
            db,
            job.user_id,
            str(payload["text"]),
            str(payload.get("intensity") or "structure"),
            payload.get("prompt"),
            payload.get("scriptId"),
            progress_callback=progress,
        )
        return rewrite_result.model_dump()
    if job.kind == "similarity":
        await progress(55, "正在分析文案重复度")
        return (await content_service.similarity(str(payload["text"]))).model_dump()
    raise RuntimeError(f"不支持的文案任务类型：{job.kind}")


async def _update_progress(job_id: str, progress: int, stage: str) -> None:
    async with SessionLocal() as db:
        job = await repository.get_job(db, job_id)
        if job is None or job.status != "running":
            return
        job.progress = max(job.progress, min(progress, 94))
        job.stage = stage
        await db.commit()
        await _emit(job)


async def recover_pending_jobs(db: AsyncSession) -> int:
    jobs = await repository.pending_jobs(db)
    for job in jobs:
        message_id = schedule_content_job(job.id)
        await repository.record_job_message(db, job.id, message_id)
    if jobs:
        logger.warning("content_jobs_recovered", count=len(jobs))
    return len(jobs)


async def _emit(job: ContentJob) -> None:
    await publish(
        CHANNEL_TASKS,
        {
            "kind": "content_job_updated",
            "jobId": job.id,
            "userId": job.user_id,
            "status": job.status,
            "progress": job.progress,
            "stage": job.stage,
        },
    )


def _billing_step(kind: str) -> str:
    return "asr" if kind.startswith("parse_") else "script_generation"


def _error_message(exc: BaseException) -> str:
    if not isinstance(exc, (HTTPException, ProviderError)):
        return str(exc)[:500] or type(exc).__name__
    return public_error_message(exc)


def to_out(job: ContentJob) -> ContentJobOut:
    result = public_metadata(json.loads(job.result_json or "{}"))
    return ContentJobOut(
        id=job.id,
        kind=job.kind,
        status=job.status,
        progress=job.progress,
        stage=job.stage,
        result=result or None,
        error="处理失败，请稍后重试" if job.error else "",
        createdAt=job.created_at.astimezone(UTC).isoformat(),
        updatedAt=job.updated_at.astimezone(UTC).isoformat(),
    )
