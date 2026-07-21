"""Webhook signature and delivery idempotency."""

import hashlib
import hmac
import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.db import SessionLocal
from app.modules.webhook.models import WebhookEvent


async def test_forged_webhook_is_rejected_and_duplicate_event_is_dispatched_once(
    client: AsyncClient, monkeypatch
) -> None:
    from app.modules.webhook import router as webhook_router
    from app.modules.webhook import service as webhook_service

    secret = "webhook-test-secret"
    monkeypatch.setattr(webhook_router._settings, "feiying_webhook_secret", secret)
    calls: list[str] = []

    async def fake_dispatch(_db, payload: dict) -> None:
        calls.append(str(payload["task_id"]))

    monkeypatch.setattr(webhook_service, "_dispatch_callback", fake_dispatch)
    payload = {
        "event_id": "event-once",
        "type": 3,
        "task_id": "provider-task-once",
        "status": 3,
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    forged = await client.post(
        "/api/v1/webhooks/hifly",
        content=body,
        headers={"Content-Type": "application/json", "X-Signature": "forged"},
    )
    assert forged.status_code == 403

    first = await client.post(
        "/api/v1/webhooks/hifly",
        content=body,
        headers={"Content-Type": "application/json", "X-Signature": signature},
    )
    duplicate = await client.post(
        "/api/v1/webhooks/hifly",
        content=body,
        headers={"Content-Type": "application/json", "X-Signature": signature},
    )

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert calls == ["provider-task-once"]


async def test_webhook_dispatch_failure_persists_context(monkeypatch) -> None:
    from app.modules.webhook import service as webhook_service

    async def fail_dispatch(_db, _payload: dict) -> None:
        raise RuntimeError("provider timeout")

    monkeypatch.setattr(webhook_service, "_dispatch_callback", fail_dispatch)
    payload = {
        "event_id": "event-failed",
        "type": 2,
        "task_id": "provider-task-failed",
        "status": 3,
    }
    async with SessionLocal() as db:
        with pytest.raises(RuntimeError, match="provider timeout"):
            await webhook_service.handle_callback(db, payload)

    async with SessionLocal() as db:
        event = (await db.execute(select(WebhookEvent).where(WebhookEvent.event_id == "event-failed"))).scalar_one()
    assert event.status == "failed"
    assert "task=provider-task-failed" in event.error_context
    assert "RuntimeError:provider timeout" in event.error_context


async def test_failed_webhook_delivery_can_be_retried(monkeypatch) -> None:
    from app.modules.webhook import service as webhook_service

    calls = 0

    async def fail_once(_db, _payload: dict) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary failure")

    monkeypatch.setattr(webhook_service, "_dispatch_callback", fail_once)
    payload = {
        "event_id": "event-retry",
        "type": 3,
        "task_id": "provider-task-retry",
        "status": 3,
    }
    async with SessionLocal() as db:
        with pytest.raises(RuntimeError, match="temporary failure"):
            await webhook_service.handle_callback(db, payload)
        processed = await webhook_service.handle_callback(db, payload)

    assert processed is True
    assert calls == 2
    async with SessionLocal() as db:
        event = (await db.execute(select(WebhookEvent).where(WebhookEvent.event_id == "event-retry"))).scalar_one()
    assert event.status == "succeeded"
    assert event.error_context == ""
