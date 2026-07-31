"""Admin password-login brute-force protection."""

import uuid

from httpx import AsyncClient
from sqlalchemy import delete

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.modules.activation.models import ActivationRateLimit
from app.modules.auth.models import User


async def _reset_admin_login_limits() -> None:
    async with SessionLocal() as db:
        await db.execute(delete(ActivationRateLimit).where(ActivationRateLimit.action == "admin_login"))
        await db.commit()


async def test_admin_login_locks_repeated_failures(client: AsyncClient, monkeypatch) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "activation_failure_limit", 2, raising=False)
    monkeypatch.setattr(settings, "activation_lock_seconds", 60, raising=False)
    await _reset_admin_login_limits()

    phone = f"139{uuid.uuid4().hex[:8]}"
    password = "Admin@12345"
    async with SessionLocal() as db:
        db.add(
            User(
                phone=phone,
                password_hash=hash_password(password),
                nickname="限流管理员",
                avatar_char="管",
                role="admin",
            )
        )
        await db.commit()

    try:
        first = await client.post("/api/admin/v1/auth/login", json={"phone": phone, "password": "wrong-1"})
        second = await client.post("/api/admin/v1/auth/login", json={"phone": phone, "password": "wrong-2"})
        locked = await client.post("/api/admin/v1/auth/login", json={"phone": phone, "password": password})

        assert [first.status_code, second.status_code, locked.status_code] == [401, 401, 429]
        assert locked.json()["detail"]["code"] == "ADMIN_LOGIN_RATE_LIMITED"
    finally:
        await _reset_admin_login_limits()


async def test_successful_admin_login_clears_prior_failures(client: AsyncClient, monkeypatch) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "activation_failure_limit", 2, raising=False)
    await _reset_admin_login_limits()

    phone = f"139{uuid.uuid4().hex[:8]}"
    password = "Admin@12345"
    async with SessionLocal() as db:
        db.add(
            User(
                phone=phone,
                password_hash=hash_password(password),
                nickname="恢复管理员",
                avatar_char="管",
                role="admin",
            )
        )
        await db.commit()

    try:
        failed = await client.post("/api/admin/v1/auth/login", json={"phone": phone, "password": "wrong"})
        succeeded = await client.post("/api/admin/v1/auth/login", json={"phone": phone, "password": password})
        failed_after_success = await client.post(
            "/api/admin/v1/auth/login",
            json={"phone": phone, "password": "wrong-again"},
        )

        assert [failed.status_code, succeeded.status_code, failed_after_success.status_code] == [401, 200, 401]
    finally:
        await _reset_admin_login_limits()
