"""文案转录、改写和分析必须通过持久后台任务执行。"""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.core.db import SessionLocal, init_models
from app.modules.content.schemas import RewriteOut


@pytest_asyncio.fixture(autouse=True)
async def _database() -> None:
    await init_models()


async def test_rewrite_submission_only_enqueues_job(monkeypatch) -> None:
    from app.modules.content import jobs
    from app.modules.content.models import ContentJob

    scheduled: list[str] = []

    async def fake_reserve(*_args, **_kwargs) -> str:
        return "rewrite-reservation"

    async def fake_attach(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(jobs, "reserve_metered_operation", fake_reserve)
    monkeypatch.setattr(jobs, "attach_reservation", fake_attach)
    monkeypatch.setattr(
        jobs,
        "schedule_content_job",
        lambda job_id: scheduled.append(job_id) or "rewrite-message",
    )
    monkeypatch.setattr(
        jobs.content_service,
        "rewrite",
        lambda *_args, **_kwargs: pytest.fail("提交接口不应同步执行模型改写"),
    )

    async with SessionLocal() as db:
        submitted = await jobs.submit_rewrite(
            db,
            user_id="async-rewrite-user",
            text="需要异步改写的原始文案",
            intensity="structure",
            prompt="保持数据不变",
            script_id=None,
            quote_id="rewrite-quote",
        )

    assert submitted.status == "pending"
    assert submitted.progress == 0
    assert scheduled == [submitted.id]

    async with SessionLocal() as db:
        stored = await db.get(ContentJob, submitted.id)
        assert stored is not None
        stored.status = "failed"
        await db.commit()


async def test_successful_job_settles_after_result_is_persisted(monkeypatch) -> None:
    from app.modules.content import jobs
    from app.modules.content.models import ContentJob

    settlements: list[tuple[str, str]] = []

    async def fake_rewrite(*_args, **_kwargs) -> RewriteOut:
        return RewriteOut(
            text="异步改写完成",
            structure={"hook_type": "提问"},
            outline="先提出问题，再给解决方案",
            similarity=12,
            validationPassed=True,
        )

    async def fake_settle(_db, reservation_id: str, task_id: str, **_kwargs) -> int:
        async with SessionLocal() as check_db:
            stored = await check_db.get(ContentJob, task_id)
            assert stored is not None
            assert stored.status == "running"
            assert "异步改写完成" in stored.result_json
        settlements.append((reservation_id, task_id))
        return 2

    monkeypatch.setattr(jobs.content_service, "rewrite", fake_rewrite)
    monkeypatch.setattr(jobs, "settle_reservation", fake_settle)
    monkeypatch.setattr(jobs, "publish", lambda *_args, **_kwargs: _noop())

    async with SessionLocal() as db:
        job = ContentJob(
            user_id="async-success-user",
            kind="rewrite",
            status="pending",
            payload_json=('{"text":"原始文案","intensity":"structure","prompt":null,"scriptId":null}'),
            reservation_id="success-reservation",
        )
        db.add(job)
        await db.commit()
        job_id = job.id

    await jobs.run_content_job(job_id)

    async with SessionLocal() as db:
        completed = await db.get(ContentJob, job_id)

    assert completed is not None
    assert completed.status == "done"
    assert completed.progress == 100
    assert settlements == [("success-reservation", job_id)]


async def test_failed_job_releases_reservation_without_settlement(monkeypatch) -> None:
    from app.modules.content import jobs
    from app.modules.content.models import ContentJob

    released: list[str] = []

    async def fail_rewrite(*_args, **_kwargs) -> RewriteOut:
        raise RuntimeError("provider timeout")

    async def fake_release(_db, reservation_id: str, _user_id: str):
        released.append(reservation_id)
        return SimpleNamespace(status="released")

    async def forbidden_settle(*_args, **_kwargs) -> int:
        pytest.fail("失败任务不得结算积分")

    monkeypatch.setattr(jobs.content_service, "rewrite", fail_rewrite)
    monkeypatch.setattr(jobs, "release_reservation", fake_release)
    monkeypatch.setattr(jobs, "settle_reservation", forbidden_settle)
    monkeypatch.setattr(jobs, "publish", lambda *_args, **_kwargs: _noop())

    async with SessionLocal() as db:
        job = ContentJob(
            user_id="async-failure-user",
            kind="rewrite",
            status="pending",
            payload_json='{"text":"原始文案","intensity":"structure"}',
            reservation_id="failed-reservation",
        )
        db.add(job)
        await db.commit()
        job_id = job.id

    await jobs.run_content_job(job_id)

    async with SessionLocal() as db:
        failed = await db.get(ContentJob, job_id)

    assert failed is not None
    assert failed.status == "failed"
    assert "provider timeout" in failed.error
    assert released == ["failed-reservation"]


async def test_recovery_does_not_duplicate_fresh_running_content_job(monkeypatch) -> None:
    from app.modules.content import jobs
    from app.modules.content.models import ContentJob

    monkeypatch.setattr(
        jobs,
        "schedule_content_job",
        lambda _job_id: (_ for _ in ()).throw(AssertionError("fresh running job must not be scheduled")),
    )

    async with SessionLocal() as db:
        job = ContentJob(
            user_id="fresh-content-user",
            kind="rewrite",
            status="running",
            payload_json='{"text":"正在处理的文案"}',
            reservation_id="fresh-content-reservation",
        )
        db.add(job)
        await db.commit()
        recovered = await jobs.recover_pending_jobs(db)
        await db.refresh(job)

    assert recovered == 0
    assert job.status == "running"


async def test_recovery_fails_stale_running_content_job_without_replaying_provider(monkeypatch) -> None:
    from app.modules.content import jobs
    from app.modules.content.models import ContentJob

    released: list[str] = []

    async def fake_release(_db, reservation_id: str, _user_id: str):
        released.append(reservation_id)
        return SimpleNamespace(status="released")

    monkeypatch.setattr(jobs, "release_reservation", fake_release)
    monkeypatch.setattr(
        jobs,
        "schedule_content_job",
        lambda _job_id: (_ for _ in ()).throw(AssertionError("stale provider call must not be replayed")),
    )

    async with SessionLocal() as db:
        job = ContentJob(
            user_id="stale-content-user",
            kind="rewrite",
            status="running",
            payload_json='{"text":"结果未持久化的文案"}',
            reservation_id="stale-content-reservation",
            updated_at=datetime.now(UTC) - timedelta(minutes=40),
        )
        db.add(job)
        await db.commit()
        recovered = await jobs.recover_pending_jobs(db)
        await db.refresh(job)

    assert recovered == 0
    assert job.status == "failed"
    assert "服务中断" in job.error
    assert released == ["stale-content-reservation"]


async def test_recovery_settles_stale_content_result_without_replaying_provider(monkeypatch) -> None:
    from app.modules.content import jobs
    from app.modules.content.models import ContentJob

    settled: list[tuple[str, str]] = []

    async def fake_settle(_db, reservation_id: str, task_id: str, **_kwargs) -> int:
        settled.append((reservation_id, task_id))
        return 2

    monkeypatch.setattr(jobs, "settle_reservation", fake_settle)
    monkeypatch.setattr(jobs, "publish", lambda *_args, **_kwargs: _noop())
    monkeypatch.setattr(
        jobs,
        "schedule_content_job",
        lambda _job_id: (_ for _ in ()).throw(AssertionError("persisted result must not rerun provider")),
    )

    async with SessionLocal() as db:
        job = ContentJob(
            user_id="settled-content-user",
            kind="rewrite",
            status="running",
            progress=95,
            stage="正在结算积分",
            payload_json='{"text":"已经处理的文案"}',
            result_json='{"text":"已经持久化的结果"}',
            reservation_id="settled-content-reservation",
            updated_at=datetime.now(UTC) - timedelta(minutes=40),
        )
        db.add(job)
        await db.commit()
        recovered = await jobs.recover_pending_jobs(db)
        await db.refresh(job)

    assert recovered == 0
    assert job.status == "done"
    assert job.progress == 100
    assert settled == [("settled-content-reservation", job.id)]


async def _noop() -> None:
    return None


def test_worker_reuses_one_event_loop_for_sequential_messages() -> None:
    from app.workers import tasks

    previous_loop = tasks._worker_loop
    tasks._worker_loop = None
    observed_loops: list[asyncio.AbstractEventLoop] = []

    async def observe_running_loop() -> None:
        observed_loops.append(asyncio.get_running_loop())

    try:
        tasks._run_async(observe_running_loop())
        tasks._run_async(observe_running_loop())
    finally:
        if tasks._worker_loop is not None:
            tasks._worker_loop.close()
        tasks._worker_loop = previous_loop

    assert observed_loops[0] is observed_loops[1]
