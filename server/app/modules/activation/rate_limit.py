"""Persistent activation brute-force protection."""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.exc import IntegrityError

from app.core.audit import write_audit
from app.core.config import get_settings
from app.core.db import SessionLocal

from .models import ActivationRateLimit


def _subject_hash(scope: str, value: str) -> str:
    settings = get_settings()
    secret = (settings.activation_secret or settings.app_secret).encode("utf-8")
    return hmac.new(secret, f"{scope}:{value}".encode(), hashlib.sha256).hexdigest()


def _subjects(ip_address: str, device_fingerprint: str, code: str) -> list[tuple[str, str]]:
    raw = (
        ("ip", ip_address.strip()),
        ("device", device_fingerprint.strip()),
        ("code", code.strip().upper()),
    )
    return [(scope, _subject_hash(scope, value)) for scope, value in raw if value]


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


async def enforce_rate_limit(action: str, *, ip_address: str, device_fingerprint: str = "", code: str = "") -> None:
    now = datetime.now(UTC)
    subjects = _subjects(ip_address, device_fingerprint, code)
    blocked_scope = ""
    async with SessionLocal() as db:
        for scope, subject_hash in subjects:
            row = (
                await db.execute(
                    select(ActivationRateLimit).where(
                        ActivationRateLimit.scope == scope,
                        ActivationRateLimit.subject_hash == subject_hash,
                        ActivationRateLimit.action == action,
                    )
                )
            ).scalar_one_or_none()
            locked_until = _as_utc(row.locked_until) if row else None
            if locked_until and locked_until > now:
                blocked_scope = scope
                break
    if blocked_scope:
        await write_audit("activation_rate_limited", detail=f"action={action},scope={blocked_scope}")
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "ACTIVATION_RATE_LIMITED", "message": "尝试次数过多，请稍后再试"},
        )


async def record_attempt(
    action: str,
    *,
    success: bool,
    ip_address: str,
    device_fingerprint: str = "",
    code: str = "",
) -> None:
    subjects = _subjects(ip_address, device_fingerprint, code)
    if success:
        if not subjects:
            return
        conditions = [
            and_(
                ActivationRateLimit.scope == scope,
                ActivationRateLimit.subject_hash == subject_hash,
                ActivationRateLimit.action == action,
            )
            for scope, subject_hash in subjects
        ]
        async with SessionLocal() as db:
            await db.execute(delete(ActivationRateLimit).where(or_(*conditions)))
            await db.commit()
        return

    for scope, subject_hash in subjects:
        await _record_failure(action, scope, subject_hash)
    await write_audit(
        "activation_attempt_failed",
        detail=f"action={action},scopes={','.join(scope for scope, _ in subjects)}",
    )


async def _record_failure(action: str, scope: str, subject_hash: str) -> None:
    settings = get_settings()
    for attempt in range(2):
        now = datetime.now(UTC)
        async with SessionLocal() as db:
            try:
                row = (
                    await db.execute(
                        select(ActivationRateLimit)
                        .where(
                            ActivationRateLimit.scope == scope,
                            ActivationRateLimit.subject_hash == subject_hash,
                            ActivationRateLimit.action == action,
                        )
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if row is None:
                    row = ActivationRateLimit(
                        scope=scope,
                        subject_hash=subject_hash,
                        action=action,
                        failure_count=0,
                        window_started_at=now,
                    )
                    db.add(row)
                window_started_at = _as_utc(row.window_started_at) or now
                if now - window_started_at > timedelta(seconds=settings.activation_rate_window_seconds):
                    row.failure_count = 0
                    row.window_started_at = now
                    row.locked_until = None
                row.failure_count += 1
                row.updated_at = now
                if row.failure_count >= settings.activation_failure_limit:
                    row.locked_until = now + timedelta(seconds=settings.activation_lock_seconds)
                await db.commit()
                return
            except IntegrityError:
                await db.rollback()
                if attempt == 1:
                    raise
