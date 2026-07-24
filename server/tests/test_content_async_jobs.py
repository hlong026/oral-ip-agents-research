"""文案转录、改写和分析必须通过持久后台任务执行。"""

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


async def _noop() -> None:
    return None
