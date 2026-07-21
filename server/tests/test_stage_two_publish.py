"""第二阶段发布能力、账号隔离和人工发布包回归测试。"""

import json
import zipfile
from io import BytesIO
from types import SimpleNamespace

import pytest_asyncio

from app.core.db import SessionLocal, init_models
from app.core.storage import read_bytes, save_bytes


@pytest_asyncio.fixture(autouse=True)
async def _database() -> None:
    await init_models()


async def test_unverified_platforms_are_export_only(monkeypatch) -> None:
    from app.modules.publish import service

    monkeypatch.setattr(
        service,
        "settings",
        SimpleNamespace(app_env="test", publish_verified_platforms=""),
    )

    capabilities = service.publish_capabilities()

    assert {item.platform for item in capabilities} == {"douyin", "xiaohongshu", "shipinhao"}
    assert all(item.mode == "export_only" for item in capabilities)
    assert all(not item.automaticEnabled for item in capabilities)


async def test_development_capability_uses_explicit_mock_driver(monkeypatch) -> None:
    from app.providers import registry as registry_module

    monkeypatch.setattr(
        registry_module,
        "get_settings",
        lambda: SimpleNamespace(app_env="dev", im_enabled=False, douyin_im_app_key=""),
    )

    dev_registry = registry_module.ProviderRegistry()

    assert all(driver.name.startswith("mock-sau-") for driver in dev_registry.publish_drivers.values())


async def test_unverified_publish_creates_export_ready_job_without_account(monkeypatch) -> None:
    from app.modules.publish import service
    from app.modules.publish.models import PublishJob

    monkeypatch.setattr(
        service,
        "settings",
        SimpleNamespace(app_env="test", publish_verified_platforms=""),
    )
    monkeypatch.setattr(service, "_schedule_job", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()))

    async with SessionLocal() as db:
        ids = await service.publish_task_video(
            db,
            "export-user",
            "pipeline-task",
            ["douyin"],
            "待人工发布标题",
            "compose/video.mp4",
            "compose/cover.jpg",
        )
        job = await db.get(PublishJob, ids[0])

    assert job is not None
    assert job.status == "export_ready"
    assert job.account_id == ""


async def test_pipeline_publish_reentry_reuses_existing_platform_job(monkeypatch) -> None:
    from app.modules.publish import repository as publish_repo
    from app.modules.publish import service

    monkeypatch.setattr(
        service,
        "settings",
        SimpleNamespace(app_env="test", publish_verified_platforms=""),
    )
    async with SessionLocal() as db:
        first = await service.publish_task_video(
            db,
            "idempotent-user",
            "same-pipeline-task",
            ["douyin"],
            "避免重复发布",
            "compose/video.mp4",
            "compose/cover.jpg",
        )
        second = await service.publish_task_video(
            db,
            "idempotent-user",
            "same-pipeline-task",
            ["douyin"],
            "避免重复发布",
            "compose/video.mp4",
            "compose/cover.jpg",
        )
        items, total = await publish_repo.list_jobs(db, "idempotent-user", None, 1, 20)

    assert first == second
    assert total == 1
    assert [item.id for item in items] == first


async def test_failed_publish_job_is_not_reused_after_account_is_fixed(monkeypatch) -> None:
    from app.modules.publish import repository as publish_repo
    from app.modules.publish import service

    monkeypatch.setattr(
        service,
        "settings",
        SimpleNamespace(app_env="test", publish_verified_platforms="douyin"),
    )
    monkeypatch.setattr(service, "_schedule_job", lambda *_args, **_kwargs: "new-message")
    async with SessionLocal() as db:
        failed = await publish_repo.create_job(
            db,
            user_id="fixed-account-user",
            task_id="retry-pipeline",
            platform="douyin",
            title="重新发布",
            video_key="compose/video.mp4",
            cover_key="compose/cover.jpg",
            topics_json="[]",
            status="failed",
            error="未授权账号",
        )
        await publish_repo.create_account(
            db,
            user_id="fixed-account-user",
            platform="douyin",
            nickname="已修复账号",
            session_json="{}",
            status="active",
        )
        created = await service.publish_task_video(
            db,
            "fixed-account-user",
            "retry-pipeline",
            ["douyin"],
            "重新发布",
            "compose/video.mp4",
            "compose/cover.jpg",
        )
        new_job = await publish_repo.get_job(db, created[0], "fixed-account-user")

    assert created != [failed.id]
    assert new_job is not None
    assert new_job.status == "queued"
    assert new_job.queue_message_id == "new-message"


async def test_changed_compose_output_does_not_reuse_old_export_job(monkeypatch) -> None:
    from app.modules.publish import repository as publish_repo
    from app.modules.publish import service

    monkeypatch.setattr(
        service,
        "settings",
        SimpleNamespace(app_env="test", publish_verified_platforms=""),
    )
    async with SessionLocal() as db:
        old = await publish_repo.create_job(
            db,
            user_id="changed-output-user",
            task_id="changed-output-task",
            platform="douyin",
            title="新成片",
            video_key="compose/old.mp4",
            cover_key="compose/old.jpg",
            topics_json="[]",
            status="export_ready",
        )
        created = await service.publish_task_video(
            db,
            "changed-output-user",
            "changed-output-task",
            ["douyin"],
            "新成片",
            "compose/new.mp4",
            "compose/new.jpg",
        )
        new_job = await publish_repo.get_job(db, created[0], "changed-output-user")

    assert created != [old.id]
    assert new_job is not None
    assert new_job.video_key == "compose/new.mp4"


async def test_export_package_contains_video_cover_and_metadata() -> None:
    from app.modules.publish import repository as publish_repo
    from app.modules.publish import service

    video_key = await save_bytes("publish-test", "video.mp4", b"video-bytes")
    cover_key = await save_bytes("publish-test", "cover.jpg", b"cover-bytes")
    async with SessionLocal() as db:
        job = await publish_repo.create_job(
            db,
            user_id="package-user",
            task_id="pipeline-1",
            platform="douyin",
            title="完整发布包",
            topics_json=json.dumps(["口播", "测试"], ensure_ascii=False),
            video_key=video_key,
            cover_key=cover_key,
            status="failed",
            error="automatic publish failed",
        )
        result = await service.export_job(db, "package-user", job.id)

    package = await read_bytes(result.packageKey)
    with zipfile.ZipFile(BytesIO(package)) as archive:
        assert set(archive.namelist()) == {"video.mp4", "cover.jpg", "metadata.json"}
        metadata = json.loads(archive.read("metadata.json"))
        assert metadata["title"] == "完整发布包"
        assert metadata["topics"] == ["口播", "测试"]
        assert metadata["platform"] == "douyin"


async def test_publish_worker_never_uses_another_users_account(monkeypatch) -> None:
    from app.modules.publish import repository as publish_repo
    from app.modules.publish import service

    called = False

    async def unexpected_publish(*_args, **_kwargs):
        nonlocal called
        called = True
        return "post-id"

    monkeypatch.setattr(
        service.registry,
        "publish_driver",
        lambda _platform: SimpleNamespace(publish=unexpected_publish),
    )
    async with SessionLocal() as db:
        account = await publish_repo.create_account(
            db,
            user_id="account-owner",
            platform="douyin",
            nickname="私有账号",
            session_json="{}",
            status="active",
        )
        job = await publish_repo.create_job(
            db,
            user_id="job-owner",
            account_id=account.id,
            platform="douyin",
            title="隔离测试",
            video_key="video.mp4",
            status="queued",
        )

    await service._run_job(job.id)

    async with SessionLocal() as db:
        stored = await publish_repo.get_job(db, job.id, "job-owner")
    assert stored is not None
    assert stored.status == "failed"
    assert "失效" in stored.error
    assert called is False
