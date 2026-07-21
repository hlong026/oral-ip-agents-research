"""Pipeline billing terminal-state regression matrix."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.billing.models import CreditLedger, CreditReservation, PriceQuote, QuotaAccount
from app.modules.billing.service import grant_points, release_reservation, reserve_quote
from app.modules.pipeline.models import PipelineTask


async def _reserved_task() -> tuple[str, str, str]:
    user_id = uuid.uuid4().hex
    quote_id = f"quote_{uuid.uuid4().hex}"
    async with SessionLocal() as db:
        db.add(
            User(
                id=user_id,
                phone=f"139{uuid.uuid4().hex[:8]}",
                password_hash=hash_password("Test@12345"),
                nickname="计费回归用户",
                role="user",
            )
        )
        await db.commit()
        await grant_points(
            db,
            user_id,
            10,
            source_type="manual",
            source_id=f"test-{uuid.uuid4().hex}",
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        db.add(
            PriceQuote(
                id=quote_id,
                user_id=user_id,
                catalog_version_id="test-catalog",
                price_version="test-v1",
                items_json="[]",
                estimated_points=4,
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
        )
        await db.commit()
        reservation = (await reserve_quote(db, user_id, quote_id)).items[0]
        task = PipelineTask(
            user_id=user_id,
            ip_id="test-ip",
            title="Pipeline 计费回归",
            script_text="可执行的测试文案",
            mode="auto",
            reservation_id=reservation.id,
        )
        db.add(task)
        await db.commit()
        return task.id, reservation.id, user_id


async def _all_steps_succeed(*_args, **_kwargs) -> dict:
    return {}


async def test_pipeline_success_settles_once(client, monkeypatch) -> None:
    from app.modules.pipeline import engine

    task_id, reservation_id, _ = await _reserved_task()
    monkeypatch.setattr(engine, "STEP_RUNNERS", dict.fromkeys(engine.STEP_ORDER, _all_steps_succeed))

    await engine.run_task(task_id)

    async with SessionLocal() as db:
        task = await db.get(PipelineTask, task_id)
        reservation = await db.get(CreditReservation, reservation_id)
        settlements = await db.scalar(
            select(func.count(CreditLedger.id)).where(
                CreditLedger.reference_id == reservation_id,
                CreditLedger.event_type == "settle",
            )
        )
    assert task is not None and task.status == "done"
    assert reservation is not None and reservation.status == "settled"
    assert settlements == 1


async def test_provider_failure_releases_pipeline_reservation(client, monkeypatch) -> None:
    from app.modules.pipeline import engine

    async def provider_fails(*_args, **_kwargs) -> dict:
        raise RuntimeError("provider unavailable")

    task_id, reservation_id, user_id = await _reserved_task()
    runners = dict.fromkeys(engine.STEP_ORDER, _all_steps_succeed)
    runners["parse"] = provider_fails
    monkeypatch.setattr(engine, "STEP_RUNNERS", runners)

    await engine.run_task(task_id)

    async with SessionLocal() as db:
        task = await db.get(PipelineTask, task_id)
        reservation = await db.get(CreditReservation, reservation_id)
        account = (await db.execute(select(QuotaAccount).where(QuotaAccount.user_id == user_id))).scalar_one()
    assert task is not None and task.status == "failed"
    assert reservation is not None and reservation.status == "released"
    assert account.balance == 10


async def test_settlement_failure_marks_task_failed_and_releases_reservation(client, monkeypatch) -> None:
    from app.modules.billing import service as billing_service
    from app.modules.pipeline import engine

    task_id, reservation_id, user_id = await _reserved_task()
    monkeypatch.setattr(engine, "STEP_RUNNERS", dict.fromkeys(engine.STEP_ORDER, _all_steps_succeed))

    async def settlement_fails(*_args, **_kwargs) -> int:
        return 0

    monkeypatch.setattr(billing_service, "settle_reservation", settlement_fails)
    await engine.run_task(task_id)

    async with SessionLocal() as db:
        task = await db.get(PipelineTask, task_id)
        reservation = await db.get(CreditReservation, reservation_id)
        account = (await db.execute(select(QuotaAccount).where(QuotaAccount.user_id == user_id))).scalar_one()
    assert task is not None and task.status == "failed"
    assert task.error == "billing: settlement failed"
    assert reservation is not None and reservation.status == "released"
    assert account.balance == 10


async def test_failed_pipeline_cannot_retry_a_released_reservation(client, monkeypatch) -> None:
    from app.modules.pipeline import service as pipeline_service

    task_id, reservation_id, user_id = await _reserved_task()
    async with SessionLocal() as db:
        task = await db.get(PipelineTask, task_id)
        assert task is not None
        task.status = "failed"
        await db.commit()
        await release_reservation(db, reservation_id, user_id)

    monkeypatch.setattr(pipeline_service, "schedule_run", lambda *_args, **_kwargs: None)
    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await pipeline_service.retry_step(db, task_id, "parse", user_id)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "RETRY_REQUIRES_NEW_QUOTE"
