"""Signed webhook dispatch with durable delivery receipts."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.logging import get_logger

from .models import WebhookEvent

logger = get_logger("oral.webhook")
settings = get_settings()


async def handle_callback(
    db: AsyncSession,
    payload: dict,
    *,
    event_id: str = "",
) -> bool:
    """Claim a delivery once, then record whether dispatch succeeded."""
    msg_type = int(payload.get("type", 0) or 0)
    task_id = str(payload.get("task_id", "") or "")
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()
    event_id = str(event_id or payload.get("event_id") or payload.get("eventId") or "")
    if not event_id:
        event_id = f"task:{msg_type}:{task_id}:{payload_hash[:16]}"

    receipt = WebhookEvent(
        provider="hifly",
        event_id=event_id[:128],
        msg_type=msg_type,
        provider_task_id=task_id[:64],
        payload_hash=payload_hash,
        payload_json=payload_json,
    )
    db.add(receipt)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = (
            await db.execute(
                select(WebhookEvent).where(
                    WebhookEvent.provider == "hifly",
                    WebhookEvent.event_id == event_id[:128],
                )
            )
        ).scalar_one_or_none()
        if existing is not None and (existing.msg_type != msg_type or existing.provider_task_id != task_id[:64]):
            logger.warning(
                "webhook_identity_collision_ignored",
                provider="hifly",
                event_id=event_id[:128],
                task_id=task_id[:64],
                msg_type=msg_type,
            )
            return False
        if existing is None:
            existing = (
                await db.execute(
                    select(WebhookEvent).where(
                        WebhookEvent.provider == "hifly",
                        WebhookEvent.msg_type == msg_type,
                        WebhookEvent.provider_task_id == task_id[:64],
                    )
                )
            ).scalar_one_or_none()
        if existing is None or existing.status != "failed":
            logger.info(
                "webhook_duplicate_ignored",
                provider="hifly",
                event_id=event_id[:128],
                task_id=task_id[:64],
                msg_type=msg_type,
            )
            return False
        claimed = await db.execute(
            update(WebhookEvent)
            .where(WebhookEvent.id == existing.id, WebhookEvent.status == "failed")
            .values(
                status="processing",
                payload_hash=payload_hash,
                payload_json=payload_json,
                error_context="",
                processed_at=None,
                next_retry_at=None,
            )
            .execution_options(synchronize_session=False)
        )
        if int(getattr(claimed, "rowcount", 0) or 0) != 1:
            await db.rollback()
            return False
        await db.commit()
        receipt = existing
        logger.info(
            "webhook_failed_delivery_retried",
            provider="hifly",
            event_id=event_id[:128],
            task_id=task_id[:64],
            msg_type=msg_type,
        )

    try:
        if not task_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "TASK_ID_REQUIRED", "message": "回调缺少 task_id"},
            )
        await _dispatch_callback(db, payload)
    except Exception as exc:
        await db.rollback()
        await _record_failure(
            db,
            receipt.id,
            payload_json,
            msg_type=msg_type,
            task_id=task_id,
            exc=exc,
        )
        logger.exception(
            "webhook_dispatch_failed",
            provider="hifly",
            event_id=event_id[:128],
            task_id=task_id[:64],
            msg_type=msg_type,
        )
        raise

    current_receipt = await db.get(WebhookEvent, receipt.id)
    if current_receipt:
        current_receipt.status = "succeeded"
        current_receipt.error_context = ""
        current_receipt.next_retry_at = None
        current_receipt.processed_at = datetime.now(UTC)
        await db.commit()
    return True


def _retry_delay_seconds(retry_count: int) -> int:
    return settings.webhook_retry_base_seconds * (2 ** max(0, retry_count))


def _schedule_webhook_retry(event_id: str, delay_ms: int) -> str:
    from app.workers.tasks import run_webhook_retry

    message = run_webhook_retry.send_with_options(args=(event_id,), delay=max(0, delay_ms))
    return message.message_id


async def _record_failure(
    db: AsyncSession,
    event_id: str,
    payload_json: str,
    *,
    msg_type: int,
    task_id: str,
    exc: Exception,
) -> None:
    receipt = await db.get(WebhookEvent, event_id)
    if receipt is None:
        return

    retry_delay = _retry_delay_seconds(receipt.retry_count)
    receipt.status = "failed"
    receipt.payload_json = payload_json
    receipt.error_context = (
        f"type={msg_type},task={task_id[:64]},error={type(exc).__name__}:{str(exc)[:300]}"
    )
    receipt.processed_at = datetime.now(UTC)
    receipt.next_retry_at = receipt.processed_at + timedelta(seconds=retry_delay)
    await db.commit()

    if receipt.retry_count >= settings.webhook_retry_max_attempts:
        return
    try:
        _schedule_webhook_retry(receipt.id, retry_delay * 1000)
    except Exception:
        logger.exception(
            "webhook_retry_enqueue_failed",
            event_id=receipt.id,
            retry_count=receipt.retry_count,
        )


async def retry_failed_event(event_id: str) -> bool:
    """Claim and replay one persisted failed callback without provider redelivery."""
    async with SessionLocal() as db:
        claimed = await db.execute(
            update(WebhookEvent)
            .where(
                WebhookEvent.id == event_id,
                WebhookEvent.status == "failed",
                WebhookEvent.retry_count < settings.webhook_retry_max_attempts,
            )
            .values(
                status="processing",
                retry_count=WebhookEvent.retry_count + 1,
                error_context="",
                processed_at=None,
                next_retry_at=None,
            )
            .execution_options(synchronize_session=False)
        )
        if int(getattr(claimed, "rowcount", 0) or 0) != 1:
            await db.rollback()
            return False
        await db.commit()

        receipt = await db.get(WebhookEvent, event_id)
        if receipt is None:
            return False
        try:
            payload = json.loads(receipt.payload_json)
            if not isinstance(payload, dict):
                raise ValueError("webhook payload must be an object")
            await _dispatch_callback(db, payload)
        except Exception as exc:
            await db.rollback()
            await _record_failure(
                db,
                receipt.id,
                receipt.payload_json,
                msg_type=receipt.msg_type,
                task_id=receipt.provider_task_id,
                exc=exc,
            )
            logger.exception(
                "webhook_internal_retry_failed",
                event_id=receipt.id,
                retry_count=receipt.retry_count,
            )
            return False

        current_receipt = await db.get(WebhookEvent, event_id)
        if current_receipt:
            current_receipt.status = "succeeded"
            current_receipt.error_context = ""
            current_receipt.next_retry_at = None
            current_receipt.processed_at = datetime.now(UTC)
            await db.commit()
        return True


async def recover_failed_webhooks(db: AsyncSession) -> int:
    """Re-enqueue persisted failed callbacks after an API restart."""
    now = datetime.now(UTC)
    events = (
        await db.execute(
            select(WebhookEvent).where(
                WebhookEvent.status == "failed",
                WebhookEvent.retry_count < settings.webhook_retry_max_attempts,
                WebhookEvent.payload_json != "{}",
            )
        )
    ).scalars()
    scheduled = 0
    for event in events:
        next_retry_at = event.next_retry_at
        if next_retry_at is not None and next_retry_at.tzinfo is None:
            next_retry_at = next_retry_at.replace(tzinfo=UTC)
        delay_ms = max(0, int(((next_retry_at or now) - now).total_seconds() * 1000))
        try:
            _schedule_webhook_retry(event.id, delay_ms)
            scheduled += 1
        except Exception:
            logger.exception("webhook_recovery_enqueue_failed", event_id=event.id)
    return scheduled


async def _dispatch_callback(db: AsyncSession, payload: dict) -> None:
    msg_type = int(payload.get("type", 0) or 0)
    task_id = str(payload.get("task_id", "") or "")
    status_code = int(payload.get("status", 0) or 0)

    if msg_type == 3:
        from app.modules.voice.service import handle_voice_callback

        await handle_voice_callback(
            db,
            task_id,
            status_code,
            str(payload.get("voice", "") or ""),
            str(payload.get("demo_url", "") or ""),
        )
    elif msg_type == 2:
        from app.modules.avatar.service import handle_avatar_callback

        await handle_avatar_callback(
            db,
            task_id,
            status_code,
            str(payload.get("avatar", "") or ""),
        )
    elif msg_type == 1:
        # Pipeline Worker 负责轮询、转存和计费；Webhook 收据只提供可审计的完成信号，
        # 避免回调与 Worker 并发改写任务状态。
        logger.info(
            "webhook_video_callback_received",
            task_id=task_id,
            provider_status=status_code,
            duration=payload.get("duration", 0),
        )
    else:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "UNSUPPORTED_WEBHOOK", "message": "不支持的回调类型"},
        )
