"""Pipeline billing terminal-state regression matrix."""

import json
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
from app.modules.notify.models import Notification
from app.modules.pipeline.models import PipelineRenderVersion, PipelineTask


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
    runners = dict.fromkeys(engine.STEP_ORDER, _all_steps_succeed)

    async def compose_succeeds(*_args, **_kwargs) -> dict:
        return {
            "final_video_key": "compose/initial.mp4",
            "cover_key": "compose/initial.jpg",
            "quality": {"passed": True},
        }

    runners["compose"] = compose_succeeds
    monkeypatch.setattr(engine, "STEP_RUNNERS", runners)

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
        notification = (
            (
                await db.execute(
                    select(Notification)
                    .where(Notification.user_id == task.user_id)
                    .order_by(Notification.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
        render = (
            await db.execute(
                select(PipelineRenderVersion).where(
                    PipelineRenderVersion.task_id == task_id,
                    PipelineRenderVersion.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
    assert task is not None and task.status == "done"
    assert reservation is not None and reservation.status == "settled"
    assert settlements == 1
    assert notification is not None and "全流程完成" in notification.title
    assert render is not None and render.version == 1 and render.status == "done"
    assert render.reservation_id == reservation_id
    assert task.active_render_version == 1
    artifacts = json.loads(task.artifacts_json)
    assert artifacts["render_version"] == 1
    assert artifacts["render_version_id"] == render.id


async def test_pipeline_settles_and_activates_render_before_publish(client, monkeypatch) -> None:
    from app.modules.pipeline import engine

    task_id, reservation_id, _ = await _reserved_task()
    runners = dict.fromkeys(engine.STEP_ORDER, _all_steps_succeed)

    async def compose_succeeds(*_args, **_kwargs) -> dict:
        return {
            "final_video_key": "compose/pre-publish.mp4",
            "cover_key": "compose/pre-publish.jpg",
            "quality": {"passed": True},
        }

    async def publish_observes_settled_render(task, ctx) -> dict:
        async with SessionLocal() as check_db:
            reservation = await check_db.get(CreditReservation, reservation_id)
            active = (
                await check_db.execute(
                    select(PipelineRenderVersion).where(
                        PipelineRenderVersion.task_id == task.id,
                        PipelineRenderVersion.is_active.is_(True),
                    )
                )
            ).scalar_one_or_none()
        assert reservation is not None and reservation.status == "settled"
        assert active is not None
        assert ctx["render_version_id"] == active.id
        assert ctx["render_version"] == active.version
        return {"publish_job_ids": ["publish-after-settlement"]}

    runners["compose"] = compose_succeeds
    runners["publish"] = publish_observes_settled_render
    monkeypatch.setattr(engine, "STEP_RUNNERS", runners)

    await engine.run_task(task_id)

    async with SessionLocal() as db:
        task = await db.get(PipelineTask, task_id)
        reservation = await db.get(CreditReservation, reservation_id)

    assert task is not None and task.status == "done"
    assert reservation is not None and reservation.status == "settled"


async def test_publish_setup_failure_keeps_paid_video_available(client, monkeypatch) -> None:
    from app.modules.pipeline import engine

    task_id, reservation_id, _ = await _reserved_task()
    runners = dict.fromkeys(engine.STEP_ORDER, _all_steps_succeed)

    async def compose_succeeds(*_args, **_kwargs) -> dict:
        return {
            "final_video_key": "compose/publish-warning.mp4",
            "cover_key": "compose/publish-warning.jpg",
            "quality": {"passed": True},
        }

    async def publish_fails(*_args, **_kwargs) -> dict:
        raise RuntimeError("publish queue unavailable")

    runners["compose"] = compose_succeeds
    runners["publish"] = publish_fails
    monkeypatch.setattr(engine, "STEP_RUNNERS", runners)

    await engine.run_task(task_id)

    async with SessionLocal() as db:
        task = await db.get(PipelineTask, task_id)
        reservation = await db.get(CreditReservation, reservation_id)
        active = (
            await db.execute(
                select(PipelineRenderVersion).where(
                    PipelineRenderVersion.task_id == task_id,
                    PipelineRenderVersion.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()

    assert task is not None and task.status == "done"
    assert reservation is not None and reservation.status == "settled"
    assert active is not None and active.video_key == "compose/publish-warning.mp4"
    publish_step = next(item for item in json.loads(task.steps_json) if item["step"] == "publish")
    assert publish_step["status"] == "failed"
    assert "发布管理" in publish_step["message"]


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
        notification = (
            (
                await db.execute(
                    select(Notification).where(Notification.user_id == user_id).order_by(Notification.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
    assert task is not None and task.status == "failed"
    assert reservation is not None and reservation.status == "released"
    assert account.balance == 10
    assert notification is not None and "任务失败" in notification.title
    assert "parse" in notification.body


async def test_unknown_provider_outcome_holds_reservation_for_reconciliation(client, monkeypatch) -> None:
    from app.modules.pipeline import engine
    from app.providers.base import ProviderOutcomeUnknown

    async def provider_outcome_unknown(*_args, **_kwargs) -> dict:
        raise ProviderOutcomeUnknown("服务提交结果未知，请先对账再重试")

    task_id, reservation_id, user_id = await _reserved_task()
    runners = dict.fromkeys(engine.STEP_ORDER, _all_steps_succeed)
    runners["voice"] = provider_outcome_unknown
    monkeypatch.setattr(engine, "STEP_RUNNERS", runners)

    await engine.run_task(task_id)

    async with SessionLocal() as db:
        task = await db.get(PipelineTask, task_id)
        reservation = await db.get(CreditReservation, reservation_id)
        account = (await db.execute(select(QuotaAccount).where(QuotaAccount.user_id == user_id))).scalar_one()
        notification = (
            (
                await db.execute(
                    select(Notification).where(Notification.user_id == user_id).order_by(Notification.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
    assert task is not None and task.status == "reconciliation_required"
    assert reservation is not None and reservation.status == "reserved"
    assert account.balance == 6
    assert notification is not None and "人工对账" in notification.title


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


async def test_retry_queue_failure_releases_reserved_points(client, monkeypatch) -> None:
    from app.modules.pipeline import service as pipeline_service

    task_id, reservation_id, user_id = await _reserved_task()
    async with SessionLocal() as db:
        task = await db.get(PipelineTask, task_id)
        assert task is not None
        task.status = "failed"
        await db.commit()

    monkeypatch.setattr(
        pipeline_service,
        "schedule_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("redis unavailable")),
    )
    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await pipeline_service.retry_step(db, task_id, "parse", user_id)

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "PIPELINE_QUEUE_UNAVAILABLE"
    async with SessionLocal() as db:
        task = await db.get(PipelineTask, task_id)
        reservation = await db.get(CreditReservation, reservation_id)
    assert task is not None and task.status == "failed"
    assert "队列" in task.error
    assert reservation is not None and reservation.status == "released"


async def test_manual_confirm_queue_failure_restores_waiting_state(client, monkeypatch) -> None:
    from app.modules.pipeline import service as pipeline_service

    task_id, _, user_id = await _reserved_task()
    async with SessionLocal() as db:
        task = await db.get(PipelineTask, task_id)
        assert task is not None
        task.status = "waiting_confirm"
        await db.commit()

    monkeypatch.setattr(
        pipeline_service,
        "schedule_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("redis unavailable")),
    )
    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await pipeline_service.confirm(db, task_id, user_id)

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "PIPELINE_QUEUE_UNAVAILABLE"
    async with SessionLocal() as db:
        task = await db.get(PipelineTask, task_id)
    assert task is not None and task.status == "waiting_confirm"
    assert task.queue_message_id == ""


async def test_rewrite_step_reuses_confirmed_script(client) -> None:
    """向导二创确认后的 script_text 即最终口播稿，rewrite 步不得重新仿写。"""
    from app.modules.pipeline import engine

    task = PipelineTask(
        user_id=uuid.uuid4().hex,
        ip_id="test-ip",
        title="二创文案复用",
        script_text="这是用户已确认的二创口播文案",
        mode="auto",
    )

    result = await engine.step_rewrite(task, {"script": task.script_text})

    assert result == {"skipped": True, "script": "这是用户已确认的二创口播文案"}


async def test_cancel_during_step_is_not_overwritten(client, monkeypatch) -> None:
    """步骤执行期间用户取消：步骤完成后的落库不得把 canceled 覆盖回 running。"""
    from app.modules.pipeline import engine

    task_id, reservation_id, user_id = await _reserved_task()

    async def cancel_while_running(*_args, **_kwargs) -> dict:
        # 模拟用户在步骤执行期间点击取消（cancel 接口会置 canceled + 释放预留）
        async with SessionLocal() as db:
            running = await db.get(PipelineTask, task_id)
            assert running is not None
            running.status = "canceled"
            await db.commit()
            await release_reservation(db, reservation_id, user_id)
        return {}

    runners = dict.fromkeys(engine.STEP_ORDER, _all_steps_succeed)
    runners["parse"] = cancel_while_running
    monkeypatch.setattr(engine, "STEP_RUNNERS", runners)

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
    assert task is not None and task.status == "canceled"
    assert reservation is not None and reservation.status == "released"
    assert settlements == 0


def test_pipeline_quote_quantities_skips_script_generation_for_confirmed_script() -> None:
    """已带确认文案的任务跳过 rewrite，服务端报价合同不含 script_generation。"""
    from app.modules.billing.service import pipeline_quote_quantities

    module_units = {
        "topic_generation": "per_action",
        "script_generation": "per_1k_tokens",
        "tts": "per_1k_chars",
        "digital_human": "per_second",
        "hd_export": "per_action",
    }

    with_script = pipeline_quote_quantities({"scriptText": "文" * 100}, module_units)
    assert with_script and "script_generation" not in with_script

    without_script = pipeline_quote_quantities({"topic": "新选题"}, module_units)
    assert "script_generation" in without_script
