"""Activation brute-force protection."""

import asyncio
import uuid

from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.audit import AuditLog
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.modules.activation.models import ActivationRateLimit


async def test_repeated_invalid_activation_codes_are_locked_then_recover(client: AsyncClient, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "activation_failure_limit", 3, raising=False)
    monkeypatch.setattr(settings, "activation_rate_window_seconds", 60, raising=False)
    monkeypatch.setattr(settings, "activation_lock_seconds", 1, raising=False)
    device = f"device-{uuid.uuid4().hex}"
    body = {"code": "ORAL-XXXX-XXXX-XXXX-XXXX-XXXX", "deviceFingerprint": device}

    attempts = [await client.post("/api/v1/activation/validate-code", json=body) for _ in range(4)]

    assert [response.status_code for response in attempts] == [200, 200, 200, 429]
    assert attempts[-1].json()["detail"]["code"] == "ACTIVATION_RATE_LIMITED"

    async with SessionLocal() as db:
        audit_events = list(
            (await db.execute(select(AuditLog).where(AuditLog.event == "activation_rate_limited"))).scalars()
        )
    assert audit_events

    await asyncio.sleep(1.1)
    recovered = await client.post("/api/v1/activation/validate-code", json=body)
    assert recovered.status_code == 200

    async with SessionLocal() as db:
        await db.execute(delete(ActivationRateLimit).where(ActivationRateLimit.action == "validate"))
        await db.commit()
