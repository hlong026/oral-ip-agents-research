"""编辑器重合成、计费幂等与产物版本回归。"""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.billing.models import CreditReservation, PriceQuote
from app.modules.billing.service import grant_points
from app.modules.pipeline.models import PipelineRenderVersion, PipelineTask
from app.modules.pipeline.schemas import EditConfigIn, RecomposeIn


def _config(*, cover_template: str = "bold-bottom") -> EditConfigIn:
    return EditConfigIn(
        subtitleStyle={
            "fontSize": 48,
            "color": "#FDE047",
            "position": "bottom",
            "stroke": 3,
        },
        bgmMode="off",
        bgmVolume=0,
        coverTemplate=cover_template,
    )


def test_apply_config_writes_subtitle_switch() -> None:
    from app.modules.pipeline.render import _apply_config

    # 默认开启；显式关闭时写入 False，重合成据此跳过 ASS 烧录
    assert _apply_config({}, _config())["subtitle_enabled"] is True
    disabled = _config()
    disabled.subtitleEnabled = False
    updated = _apply_config({"tts_words": [{"word": "测", "start": 0.0, "end": 0.3}]}, disabled)
    assert updated["subtitle_enabled"] is False
    # 样式配置保留，便于重新开启后恢复
    assert updated["subtitle_style"]["fontSize"] == 48


def test_render_to_out_backfills_subtitle_enabled_for_legacy_config() -> None:
    from app.modules.pipeline.service import render_to_out

    # 存量 config_json 无 subtitleEnabled 字段 → 出参契约按默认值补齐为开启
    legacy = PipelineRenderVersion(
        id="render-legacy",
        task_id="task-legacy",
        version=1,
        base_version=0,
        status="done",
        config_json=(
            '{"bgmMode":"off","bgmVolume":0,"coverTemplate":"bold-bottom",'
            '"subtitleStyle":{"fontSize":44,"color":"#FFFFFF","position":"bottom","stroke":2}}'
        ),
        video_key="",
        cover_key="",
        quality_json="{}",
        error="",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    out = render_to_out(legacy)
    assert out.config.subtitleEnabled is True


async def _done_task_with_quote() -> tuple[str, str, str]:
    user_id = uuid.uuid4().hex
    quote_id = f"quote_{uuid.uuid4().hex}"
    async with SessionLocal() as db:
        db.add(
            User(
                id=user_id,
                phone=f"138{uuid.uuid4().hex[:8]}",
                password_hash=hash_password("Test@12345"),
                nickname="重合成回归用户",
                role="user",
            )
        )
        await db.commit()
        await grant_points(
            db,
            user_id,
            20,
            source_type="manual",
            source_id=f"recompose-{uuid.uuid4().hex}",
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        db.add(
            PriceQuote(
                id=quote_id,
                user_id=user_id,
                catalog_version_id="test-catalog",
                price_version="test-v1",
                items_json=json.dumps(
                    [
                        {
                            "module": "hd_export",
                            "name": "视频合成导出",
                            "quantity": 1,
                            "unit": "per_action",
                            "points": 3,
                        }
                    ],
                    ensure_ascii=False,
                ),
                estimated_points=3,
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
        )
        task = PipelineTask(
            user_id=user_id,
            ip_id="test-ip",
            title="已完成成片",
            script_text="这是已经完成的口播文案",
            status="done",
            artifacts_json=json.dumps(
                {
                    "script": "这是已经完成的口播文案",
                    "avatar_video_key": "avatar/source.mp4",
                    "audio_key": "tts/voice.mp3",
                    "words": [{"word": "测", "start": 0.0, "end": 0.3}],
                    "final_video_key": "compose/v1.mp4",
                    "cover_key": "compose/v1.jpg",
                    "quality": {"passed": True},
                },
                ensure_ascii=False,
            ),
        )
        db.add(task)
        await db.commit()
        return task.id, user_id, quote_id


async def test_recompose_is_idempotent_and_reserves_once(client, monkeypatch) -> None:
    from app.modules.pipeline import service

    task_id, user_id, quote_id = await _done_task_with_quote()
    scheduled: list[str] = []
    monkeypatch.setattr(
        service,
        "schedule_render",
        lambda render_id: scheduled.append(render_id) or "render-message",
    )
    request = RecomposeIn(
        quoteId=quote_id,
        idempotencyKey=f"editor-{uuid.uuid4().hex}",
        baseVersion=1,
        config=_config(),
    )

    async with SessionLocal() as db:
        first = await service.recompose(db, task_id, user_id, request)
    async with SessionLocal() as db:
        duplicate = await service.recompose(db, task_id, user_id, request)
        count = await db.scalar(
            select(func.count(PipelineRenderVersion.id)).where(PipelineRenderVersion.task_id == task_id)
        )
        reservation_count = await db.scalar(
            select(func.count(CreditReservation.id)).where(CreditReservation.user_id == user_id)
        )

    assert first.id == duplicate.id
    assert first.version == 2
    assert first.status == "pending"
    assert "reservationId" not in first.model_dump()
    assert count == 2  # v1 由旧任务产物补建，v2 为本次重合成
    assert reservation_count == 1
    assert scheduled == [first.id]


async def test_recompose_rejects_stale_base_version_before_consuming_quote(client, monkeypatch) -> None:
    from app.modules.pipeline import service

    task_id, user_id, quote_id = await _done_task_with_quote()
    monkeypatch.setattr(service, "schedule_render", lambda _render_id: "render-message")

    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await service.recompose(
                db,
                task_id,
                user_id,
                RecomposeIn(
                    quoteId=quote_id,
                    idempotencyKey=f"editor-{uuid.uuid4().hex}",
                    baseVersion=2,
                    config=_config(),
                ),
            )
        quote = await db.get(PriceQuote, quote_id)

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "RENDER_VERSION_CONFLICT"
    assert quote is not None and quote.status == "quoted"


async def test_successful_recompose_settles_and_atomically_switches_active_version(client, monkeypatch) -> None:
    from app.modules.pipeline import render, service

    task_id, user_id, quote_id = await _done_task_with_quote()
    monkeypatch.setattr(service, "schedule_render", lambda _render_id: "render-message")
    async with SessionLocal() as db:
        created = await service.recompose(
            db,
            task_id,
            user_id,
            RecomposeIn(
                quoteId=quote_id,
                idempotencyKey=f"editor-{uuid.uuid4().hex}",
                baseVersion=1,
                config=_config(cover_template="center-band"),
            ),
        )

    async def fake_compose(_task: PipelineTask, ctx: dict) -> dict:
        assert ctx["cover_template"] == "center-band"
        assert ctx["bgm_mode"] == "off"
        assert ctx["bgm_volume"] == 0.0
        return {
            "final_video_key": "compose/v2.mp4",
            "cover_key": "compose/v2.jpg",
            "duration": 12.5,
            "quality": {"passed": True},
            "provider": "ffmpeg-local",
        }

    monkeypatch.setattr(render, "_compose_with_ctx", fake_compose)
    await render.run_render_version(created.id)

    async with SessionLocal() as db:
        task = await db.get(PipelineTask, task_id)
        current = await db.get(PipelineRenderVersion, created.id)
        versions = list(
            (
                await db.execute(
                    select(PipelineRenderVersion)
                    .where(PipelineRenderVersion.task_id == task_id)
                    .order_by(PipelineRenderVersion.version)
                )
            )
            .scalars()
            .all()
        )
        reservation = await db.get(CreditReservation, current.reservation_id if current else "")

    assert task is not None and task.active_render_version == 2
    assert current is not None and current.status == "done" and current.is_active is True
    assert [version.is_active for version in versions] == [False, True]
    assert reservation is not None and reservation.status == "settled"
    artifacts = json.loads(task.artifacts_json)
    assert artifacts["final_video_key"] == "compose/v2.mp4"
    assert artifacts["cover_key"] == "compose/v2.jpg"
    assert artifacts["render_version"] == 2
    assert artifacts["edit_config"]["coverTemplate"] == "center-band"


async def test_failed_recompose_preserves_previous_active_artifact_and_releases_quote(client, monkeypatch) -> None:
    from app.modules.pipeline import render, service

    task_id, user_id, quote_id = await _done_task_with_quote()
    monkeypatch.setattr(service, "schedule_render", lambda _render_id: "render-message")
    async with SessionLocal() as db:
        created = await service.recompose(
            db,
            task_id,
            user_id,
            RecomposeIn(
                quoteId=quote_id,
                idempotencyKey=f"editor-{uuid.uuid4().hex}",
                baseVersion=1,
                config=_config(),
            ),
        )

    async def failed_compose(_task: PipelineTask, _ctx: dict) -> dict:
        raise RuntimeError("ffmpeg failed")

    monkeypatch.setattr(render, "_compose_with_ctx", failed_compose)
    await render.run_render_version(created.id)

    async with SessionLocal() as db:
        task = await db.get(PipelineTask, task_id)
        current = await db.get(PipelineRenderVersion, created.id)
        reservation = await db.get(CreditReservation, current.reservation_id if current else "")

    assert task is not None and task.active_render_version == 1
    assert json.loads(task.artifacts_json)["final_video_key"] == "compose/v1.mp4"
    assert current is not None and current.status == "failed" and current.is_active is False
    assert reservation is not None and reservation.status == "released"


async def test_recompose_rejects_quality_result_without_video_artifact(client, monkeypatch) -> None:
    from app.modules.pipeline import render, service

    task_id, user_id, quote_id = await _done_task_with_quote()
    monkeypatch.setattr(service, "schedule_render", lambda _render_id: "render-message")
    async with SessionLocal() as db:
        created = await service.recompose(
            db,
            task_id,
            user_id,
            RecomposeIn(
                quoteId=quote_id,
                idempotencyKey=f"editor-{uuid.uuid4().hex}",
                baseVersion=1,
                config=_config(),
            ),
        )

    async def missing_video(_task: PipelineTask, _ctx: dict) -> dict:
        return {
            "final_video_key": "",
            "cover_key": "compose/invalid.jpg",
            "quality": {"passed": True},
        }

    monkeypatch.setattr(render, "_compose_with_ctx", missing_video)
    await render.run_render_version(created.id)

    async with SessionLocal() as db:
        task = await db.get(PipelineTask, task_id)
        current = await db.get(PipelineRenderVersion, created.id)
        reservation = await db.get(CreditReservation, current.reservation_id if current else "")

    assert task is not None and task.active_render_version == 1
    assert current is not None and current.status == "failed"
    assert reservation is not None and reservation.status == "released"


async def test_cancel_pending_recompose_preserves_previous_version(client, monkeypatch) -> None:
    from app.modules.pipeline import service

    task_id, user_id, quote_id = await _done_task_with_quote()
    monkeypatch.setattr(service, "schedule_render", lambda _render_id: "render-message")
    async with SessionLocal() as db:
        created = await service.recompose(
            db,
            task_id,
            user_id,
            RecomposeIn(
                quoteId=quote_id,
                idempotencyKey=f"editor-{uuid.uuid4().hex}",
                baseVersion=1,
                config=_config(),
            ),
        )
    async with SessionLocal() as db:
        canceled = await service.cancel_render(db, task_id, created.id, user_id)
        task = await db.get(PipelineTask, task_id)
        render = await db.get(PipelineRenderVersion, canceled.id)
        reservation = await db.get(CreditReservation, render.reservation_id if render else "")

    assert canceled.status == "canceled"
    assert task is not None and task.active_render_version == 1
    assert reservation is not None and reservation.status == "released"


async def test_running_recompose_cannot_be_refunded_by_cancel(client, monkeypatch) -> None:
    from app.modules.pipeline import service

    task_id, user_id, quote_id = await _done_task_with_quote()
    monkeypatch.setattr(service, "schedule_render", lambda _render_id: "render-message")
    async with SessionLocal() as db:
        created = await service.recompose(
            db,
            task_id,
            user_id,
            RecomposeIn(
                quoteId=quote_id,
                idempotencyKey=f"editor-{uuid.uuid4().hex}",
                baseVersion=1,
                config=_config(),
            ),
        )
        render = await db.get(PipelineRenderVersion, created.id)
        assert render is not None
        render.status = "running"
        await db.commit()

    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await service.cancel_render(db, task_id, created.id, user_id)
        current = await db.get(PipelineRenderVersion, created.id)
        reservation = await db.get(CreditReservation, current.reservation_id if current else "")

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "RENDER_ALREADY_RUNNING"
    assert current is not None and current.status == "running"
    assert reservation is not None and reservation.status == "reserved"


async def test_cancel_loses_race_when_worker_claims_pending_render(client, monkeypatch) -> None:
    from app.modules.pipeline import repository as pipeline_repo
    from app.modules.pipeline import service

    task_id, user_id, quote_id = await _done_task_with_quote()
    monkeypatch.setattr(service, "schedule_render", lambda _render_id: "render-message")
    async with SessionLocal() as db:
        created = await service.recompose(
            db,
            task_id,
            user_id,
            RecomposeIn(
                quoteId=quote_id,
                idempotencyKey=f"editor-{uuid.uuid4().hex}",
                baseVersion=1,
                config=_config(),
            ),
        )

    original_cancel = pipeline_repo.cancel_pending_render

    async def worker_claims_first(db, render_id: str, render_user_id: str, render_task_id: str) -> bool:
        async with SessionLocal() as worker_db:
            claimed = await pipeline_repo.claim_render(worker_db, render_id)
            assert claimed is not None and claimed.status == "running"
        return await original_cancel(db, render_id, render_user_id, render_task_id)

    monkeypatch.setattr(pipeline_repo, "cancel_pending_render", worker_claims_first)
    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await service.cancel_render(db, task_id, created.id, user_id)
    async with SessionLocal() as db:
        current = await db.get(PipelineRenderVersion, created.id)
        reservation = await db.get(CreditReservation, current.reservation_id if current else "")

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "RENDER_ALREADY_RUNNING"
    assert current is not None and current.status == "running"
    assert reservation is not None and reservation.status == "reserved"


async def test_bound_recompose_reservation_cannot_be_released_via_public_api(client, monkeypatch) -> None:
    from app.modules.billing.router import api_release_reservation
    from app.modules.pipeline import service

    task_id, user_id, quote_id = await _done_task_with_quote()
    monkeypatch.setattr(service, "schedule_render", lambda _render_id: "render-message")
    async with SessionLocal() as db:
        created = await service.recompose(
            db,
            task_id,
            user_id,
            RecomposeIn(
                quoteId=quote_id,
                idempotencyKey=f"editor-{uuid.uuid4().hex}",
                baseVersion=1,
                config=_config(),
            ),
        )
        render = await db.get(PipelineRenderVersion, created.id)
        assert render is not None
        with pytest.raises(HTTPException) as exc:
            await api_release_reservation(render.reservation_id, user_id, db)
        reservation = await db.get(CreditReservation, render.reservation_id)

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "RESERVATION_BOUND"
    assert reservation is not None and reservation.status == "reserved"


async def test_recompose_queue_failure_releases_points_and_returns_unavailable(client, monkeypatch) -> None:
    from app.modules.pipeline import repository as pipeline_repo
    from app.modules.pipeline import service

    task_id, user_id, quote_id = await _done_task_with_quote()
    idempotency_key = f"editor-{uuid.uuid4().hex}"

    def queue_fails(_render_id: str) -> str:
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(service, "schedule_render", queue_fails)
    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await service.recompose(
                db,
                task_id,
                user_id,
                RecomposeIn(
                    quoteId=quote_id,
                    idempotencyKey=idempotency_key,
                    baseVersion=1,
                    config=_config(),
                ),
            )
    async with SessionLocal() as db:
        render = await pipeline_repo.get_render_by_idempotency(db, user_id, idempotency_key)
        reservation = await db.get(CreditReservation, render.reservation_id if render else "")

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "RENDER_QUEUE_UNAVAILABLE"
    assert render is not None and render.status == "failed"
    assert reservation is not None and reservation.status == "released"


async def test_queue_receipt_failure_keeps_accepted_render_reserved_for_worker(client, monkeypatch) -> None:
    from app.modules.pipeline import repository as pipeline_repo
    from app.modules.pipeline import service

    task_id, user_id, quote_id = await _done_task_with_quote()
    monkeypatch.setattr(service, "schedule_render", lambda _render_id: "accepted-message")

    async def receipt_fails(*_args, **_kwargs) -> None:
        raise RuntimeError("database receipt unavailable")

    monkeypatch.setattr(pipeline_repo, "record_render_queue_message", receipt_fails)
    async with SessionLocal() as db:
        created = await service.recompose(
            db,
            task_id,
            user_id,
            RecomposeIn(
                quoteId=quote_id,
                idempotencyKey=f"editor-{uuid.uuid4().hex}",
                baseVersion=1,
                config=_config(),
            ),
        )
    async with SessionLocal() as db:
        render = await db.get(PipelineRenderVersion, created.id)
        reservation = await db.get(CreditReservation, render.reservation_id if render else "")

    assert created.status == "pending"
    assert render is not None and render.status == "pending" and render.queue_message_id == ""
    assert reservation is not None and reservation.status == "reserved"


async def test_recovery_requeues_only_expired_running_render(client, monkeypatch) -> None:
    from app.modules.pipeline import service

    task_id, user_id, quote_id = await _done_task_with_quote()
    monkeypatch.setattr(service, "schedule_render", lambda _render_id: "initial-message")
    async with SessionLocal() as db:
        created = await service.recompose(
            db,
            task_id,
            user_id,
            RecomposeIn(
                quoteId=quote_id,
                idempotencyKey=f"editor-{uuid.uuid4().hex}",
                baseVersion=1,
                config=_config(),
            ),
        )
        render = await db.get(PipelineRenderVersion, created.id)
        assert render is not None
        render.status = "running"
        render.updated_at = datetime.now(UTC)
        await db.commit()

    scheduled: list[str] = []
    monkeypatch.setattr(
        service,
        "schedule_render",
        lambda render_id: scheduled.append(render_id) or "replacement-message",
    )
    async with SessionLocal() as db:
        fresh_count = await service.recover_render_versions(db)
        fresh = await db.get(PipelineRenderVersion, created.id)
        assert fresh is not None
        fresh.updated_at = datetime.now(UTC) - timedelta(hours=1)
        await db.commit()
    async with SessionLocal() as db:
        stale_count = await service.recover_render_versions(db)
        recovered = await db.get(PipelineRenderVersion, created.id)

    assert fresh_count == 0
    assert stale_count == 1
    assert scheduled == [created.id]
    assert recovered is not None and recovered.status == "pending"
    assert recovered.queue_message_id == "replacement-message"


async def test_recompose_after_canceled_version_uses_next_history_number(client, monkeypatch) -> None:
    from app.modules.pipeline import service

    task_id, user_id, first_quote_id = await _done_task_with_quote()
    monkeypatch.setattr(service, "schedule_render", lambda _render_id: "render-message")
    async with SessionLocal() as db:
        canceled_candidate = await service.recompose(
            db,
            task_id,
            user_id,
            RecomposeIn(
                quoteId=first_quote_id,
                idempotencyKey=f"editor-{uuid.uuid4().hex}",
                baseVersion=1,
                config=_config(),
            ),
        )
    async with SessionLocal() as db:
        await service.cancel_render(db, task_id, canceled_candidate.id, user_id)
        second_quote_id = f"quote_{uuid.uuid4().hex}"
        db.add(
            PriceQuote(
                id=second_quote_id,
                user_id=user_id,
                catalog_version_id="test-catalog",
                price_version="test-v1",
                items_json=json.dumps(
                    [
                        {
                            "module": "hd_export",
                            "name": "视频合成导出",
                            "quantity": 1,
                            "unit": "per_action",
                            "points": 3,
                        }
                    ],
                    ensure_ascii=False,
                ),
                estimated_points=3,
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
        )
        await db.commit()
    async with SessionLocal() as db:
        replacement = await service.recompose(
            db,
            task_id,
            user_id,
            RecomposeIn(
                quoteId=second_quote_id,
                idempotencyKey=f"editor-{uuid.uuid4().hex}",
                baseVersion=1,
                config=_config(),
            ),
        )

    assert canceled_candidate.version == 2
    assert replacement.baseVersion == 1
    assert replacement.version == 3


def test_ffmpeg_bgm_uses_dynamic_volume_and_sidechain() -> None:
    from app.providers.real import _compose_command

    command = _compose_command(
        Path("/tmp/video.mp4"),
        Path("/tmp/voice.mp3"),
        Path("/tmp/bgm.mp3"),
        None,
        None,
        Path("/tmp/output.mp4"),
        1080,
        1920,
        bgm_volume=0.27,
    )
    filters = command[command.index("-filter_complex") + 1]

    assert "volume=0.27" in filters
    assert "sidechaincompress=" in filters
    assert "amix=inputs=2" in filters
