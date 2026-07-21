"""第二阶段持久化队列与重启恢复回归测试。"""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest_asyncio

from app.core.db import SessionLocal, init_models


@pytest_asyncio.fixture(autouse=True)
async def _database() -> None:
    await init_models()


async def test_pipeline_schedule_uses_dramatiq_message() -> None:
    from app.modules.pipeline.engine import schedule_run

    message_id = schedule_run("persistent-task", "voice")

    assert len(message_id) >= 16


async def test_scheduled_publish_uses_broker_delay_without_sleep(monkeypatch) -> None:
    from app.modules.publish import service
    from app.workers import tasks

    captured: dict[str, object] = {}

    def fake_send_with_options(*, args: tuple, delay: int | None = None, **_options):
        captured.update(args=args, delay=delay)
        return SimpleNamespace(message_id="publish-message")

    monkeypatch.setattr(tasks.run_publish_job, "send_with_options", fake_send_with_options)
    scheduled_at = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()

    message_id = service._schedule_job("publish-job", scheduled_at)

    assert message_id == "publish-message"
    assert captured["args"] == ("publish-job",)
    assert 295_000 <= int(captured["delay"] or 0) <= 300_000


async def test_pipeline_rewrite_similarity_receives_source_reference(monkeypatch) -> None:
    from app.modules.pipeline import engine
    from app.modules.pipeline.models import PipelineTask
    from app.providers.base import SimilarityResult

    calls: list[tuple[str, tuple]] = []

    async def fake_fallback(_kind, _chain, method, *args, **_kwargs):
        calls.append((method, args))
        if method == "polish_light":
            return "改写后的内容", "test-llm"
        if method == "check_similarity":
            return SimilarityResult(score=12.5), "local-similarity"
        raise AssertionError(f"unexpected provider call: {method}")

    monkeypatch.setattr(engine.registry, "run_with_fallback", fake_fallback)
    task = PipelineTask(
        id="rewrite-reference",
        user_id="rewrite-user",
        script_text="需要改写的原文",
        intensity="light",
    )

    result = await engine.step_rewrite(task, {})

    assert result["similarity"] == 12.5
    assert ("check_similarity", ("改写后的内容", "需要改写的原文")) in calls


async def test_running_pipeline_is_requeued_from_failed_step(monkeypatch) -> None:
    from app.modules.pipeline import repository as pipeline_repo
    from app.modules.pipeline import service

    scheduled: list[tuple[str, str | None]] = []

    def fake_schedule(task_id: str, from_step: str | None = None) -> str:
        scheduled.append((task_id, from_step))
        return "recovered-message"

    monkeypatch.setattr(service, "schedule_run", fake_schedule)

    async with SessionLocal() as db:
        task = await pipeline_repo.create(
            db,
            user_id="queue-user",
            status="running",
            current_step="avatar",
            queue_message_id="old-message",
            artifacts_json=json.dumps({"avatar_render_task_id": "persisted-render-id"}),
        )
        recovered = await service.recover_incomplete_tasks(db)
        await db.refresh(task)

    assert recovered == 1
    assert scheduled == [(task.id, "avatar")]
    assert task.status == "pending"
    assert task.queue_message_id == "recovered-message"


async def test_pipeline_task_can_only_be_claimed_once() -> None:
    from app.modules.pipeline import repository as pipeline_repo

    async with SessionLocal() as db:
        task = await pipeline_repo.create(db, user_id="claim-user", status="pending")
        await db.commit()

    async with SessionLocal() as first_db:
        first = await pipeline_repo.claim_for_run(first_db, task.id)
    async with SessionLocal() as second_db:
        second = await pipeline_repo.claim_for_run(second_db, task.id)
    async with SessionLocal() as cleanup_db:
        claimed = await pipeline_repo.get(cleanup_db, task.id)
        assert claimed is not None
        claimed.status = "canceled"
        await cleanup_db.commit()

    assert first is not None
    assert first.status == "running"
    assert second is None


async def test_running_voice_is_not_replayed_after_restart(monkeypatch) -> None:
    from app.modules.pipeline import repository as pipeline_repo
    from app.modules.pipeline import service

    scheduled: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        service,
        "schedule_run",
        lambda task_id, from_step=None: scheduled.append((task_id, from_step)) or "unexpected",
    )

    async with SessionLocal() as db:
        task = await pipeline_repo.create(
            db,
            user_id="unknown-voice-user",
            status="running",
            current_step="voice",
            queue_message_id="lost-worker-message",
        )
        recovered = await service.recover_incomplete_tasks(db)
        await db.refresh(task)

    assert recovered == 0
    assert scheduled == []
    assert task.status == "failed"
    assert "避免重复调用" in task.error


async def test_running_avatar_without_provider_task_id_is_not_replayed(monkeypatch) -> None:
    from app.modules.pipeline import repository as pipeline_repo
    from app.modules.pipeline import service

    scheduled: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        service,
        "schedule_run",
        lambda task_id, from_step=None: scheduled.append((task_id, from_step)) or "unexpected",
    )

    async with SessionLocal() as db:
        task = await pipeline_repo.create(
            db,
            user_id="unknown-avatar-user",
            status="running",
            current_step="avatar",
            queue_message_id="lost-worker-message",
        )
        recovered = await service.recover_incomplete_tasks(db)
        await db.refresh(task)

    assert recovered == 0
    assert scheduled == []
    assert task.status == "failed"
    assert "避免重复调用" in task.error


async def test_avatar_resume_reuses_persisted_provider_task(monkeypatch) -> None:
    from app.modules.pipeline import engine
    from app.modules.pipeline.models import PipelineTask

    calls: list[str] = []

    async def fake_resolve(*_args) -> str:
        return "provider-avatar"

    async def fake_fallback(_kind, _chain, method, *args, **_kwargs):
        calls.append(method)
        if method == "poll_video_task":
            assert args == ("persisted-render-id",)
            return {"video_url": "https://provider.example/video.mp4", "duration": 12}, "avatar-provider"
        if method == "download_video":
            return "stored/avatar.mp4", "avatar-provider"
        raise AssertionError(f"unexpected provider call: {method}")

    monkeypatch.setattr("app.modules.avatar.service.resolve_provider_avatar_id", fake_resolve)
    monkeypatch.setattr(engine.registry, "run_with_fallback", fake_fallback)
    task = PipelineTask(id="avatar-resume", user_id="avatar-user", avatar_id="avatar-local")

    result = await engine.step_avatar(
        task,
        {"audio_key": "audio.wav", "avatar_render_task_id": "persisted-render-id"},
    )

    assert calls == ["poll_video_task", "download_video"]
    assert result["avatar_video_key"] == "stored/avatar.mp4"


async def test_publish_recovery_never_repeats_unknown_publish(monkeypatch) -> None:
    from app.modules.publish import repository as publish_repo
    from app.modules.publish import service

    monkeypatch.setattr(service, "_schedule_job", lambda _job_id, _scheduled_at="": "queued-again")

    async with SessionLocal() as db:
        queued = await publish_repo.create_job(
            db,
            user_id="publish-user",
            platform="douyin",
            status="queued",
            queue_message_id="",
        )
        unknown = await publish_repo.create_job(
            db,
            user_id="publish-user",
            platform="douyin",
            status="publishing",
            queue_message_id="old-message",
        )
        recovered = await service.recover_publish_jobs(db)
        await db.refresh(queued)
        await db.refresh(unknown)

    assert recovered == 1
    assert queued.queue_message_id == "queued-again"
    assert unknown.status == "failed"
    assert "避免重复发布" in unknown.error
