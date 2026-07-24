"""登录防爆破：持久化失败计数 + 锁定（与激活频控同构，复用 activation_rate_limits 表）。

- 计数维度：手机号 + 来源 IP（HMAC 脱敏落库，不存明文）
- 仅对「凭据错误」计数；账号停用/未激活等其他失败不计，避免被利用锁定他人账号
- 成功登录后立即清除该主体全部失败计数
- 阈值由 LOGIN_FAILURE_LIMIT / LOGIN_RATE_WINDOW_SECONDS / LOGIN_LOCK_SECONDS 控制

并发正确性说明：增量路径依赖 SELECT ... FOR UPDATE 行锁，生产 Postgres 生效；
SQLite（dev/test）方言静默忽略 FOR UPDATE，并发下可能少计数（方向偏安全，不会多锁），
插入竞态由唯一约束 + IntegrityError 重试覆盖。
"""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.exc import IntegrityError

from app.core.audit import write_audit
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.modules.activation.models import ActivationRateLimit

_ACTION = "login"


def _subject_hash(scope: str, value: str) -> str:
    settings = get_settings()
    return hmac.new(settings.app_secret.encode(), f"login:{scope}:{value}".encode(), hashlib.sha256).hexdigest()


def _subjects(phone: str, ip_address: str) -> list[tuple[str, str]]:
    raw = (("phone", phone.strip()), ("ip", ip_address.strip()))
    return [(scope, _subject_hash(scope, value)) for scope, value in raw if value]


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


async def enforce_login_rate_limit(phone: str, ip_address: str) -> None:
    """登录前检查：任一主体处于锁定期则拒绝（429）。"""
    now = datetime.now(UTC)
    blocked_scope = ""
    async with SessionLocal() as db:
        for scope, subject_hash in _subjects(phone, ip_address):
            row = (
                await db.execute(
                    select(ActivationRateLimit).where(
                        ActivationRateLimit.scope == scope,
                        ActivationRateLimit.subject_hash == subject_hash,
                        ActivationRateLimit.action == _ACTION,
                    )
                )
            ).scalar_one_or_none()
            locked_until = _as_utc(row.locked_until) if row else None
            if locked_until and locked_until > now:
                blocked_scope = scope
                break
    if blocked_scope:
        await write_audit("login_rate_limited", detail=f"scope={blocked_scope}")
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "LOGIN_RATE_LIMITED", "message": "尝试次数过多，请稍后再试"},
        )


async def record_login_success(phone: str, ip_address: str) -> None:
    """登录成功：清除该手机号与 IP 的全部失败计数。"""
    subjects = _subjects(phone, ip_address)
    if not subjects:
        return
    conditions = [
        and_(
            ActivationRateLimit.scope == scope,
            ActivationRateLimit.subject_hash == subject_hash,
            ActivationRateLimit.action == _ACTION,
        )
        for scope, subject_hash in subjects
    ]
    async with SessionLocal() as db:
        await db.execute(delete(ActivationRateLimit).where(or_(*conditions)))
        await db.commit()


async def record_login_failure(phone: str, ip_address: str) -> None:
    """登录凭据错误：按主体累加窗口内失败次数，达限后锁定。"""
    for scope, subject_hash in _subjects(phone, ip_address):
        await _record_failure(scope, subject_hash)


async def _record_failure(scope: str, subject_hash: str) -> None:
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
                            ActivationRateLimit.action == _ACTION,
                        )
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if row is None:
                    row = ActivationRateLimit(
                        scope=scope,
                        subject_hash=subject_hash,
                        action=_ACTION,
                        failure_count=0,
                        window_started_at=now,
                    )
                    db.add(row)
                window_started_at = _as_utc(row.window_started_at) or now
                if now - window_started_at > timedelta(seconds=settings.login_rate_window_seconds):
                    row.failure_count = 0
                    row.window_started_at = now
                    row.locked_until = None
                row.failure_count += 1
                row.updated_at = now
                if row.failure_count >= settings.login_failure_limit:
                    row.locked_until = now + timedelta(seconds=settings.login_lock_seconds)
                await db.commit()
                return
            except IntegrityError:
                await db.rollback()
                if attempt == 1:
                    raise
