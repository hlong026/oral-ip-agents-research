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


async def test_manual_publish_pins_the_active_render_version(monkeypatch) -> None:
    from app.modules.pipeline.models import PipelineRenderVersion, PipelineTask
    from app.modules.publish import service
    from app.modules.publish.models import PublishJob
    from app.modules.publish.schemas import PublishIn

    monkeypatch.setattr(
        service,
        "settings",
        SimpleNamespace(app_env="test", publish_verified_platforms=""),
    )
    async with SessionLocal() as db:
        task = PipelineTask(
            user_id="render-publish-user",
            ip_id="ip-1",
            title="发布活动成片",
            status="done",
            active_render_version=2,
            artifacts_json=json.dumps(
                {
                    "final_video_key": "compose/stale-v1.mp4",
                    "cover_key": "compose/stale-v1.jpg",
                    "quality": {"passed": True},
                }
            ),
        )
        db.add(task)
        await db.flush()
        db.add_all(
            [
                PipelineRenderVersion(
                    task_id=task.id,
                    user_id=task.user_id,
                    version=1,
                    base_version=0,
                    status="done",
                    config_json='{"bgmMode":"off","bgmVolume":0,"coverTemplate":"bold-bottom","subtitleStyle":{"fontSize":44,"color":"#FFFFFF","position":"bottom","stroke":2}}',
                    idempotency_key=f"pipeline:{task.id}:1",
                    video_key="compose/v1.mp4",
                    cover_key="compose/v1.jpg",
                    quality_json='{"passed":true}',
                    is_active=False,
                ),
                PipelineRenderVersion(
                    task_id=task.id,
                    user_id=task.user_id,
                    version=2,
                    base_version=1,
                    status="done",
                    config_json='{"bgmMode":"off","bgmVolume":0,"coverTemplate":"center-band","subtitleStyle":{"fontSize":48,"color":"#FDE047","position":"top","stroke":3}}',
                    idempotency_key=f"editor:{task.id}:2",
                    video_key="compose/v2.mp4",
                    cover_key="compose/v2.jpg",
                    quality_json='{"passed":true}',
                    is_active=True,
                ),
            ]
        )
        await db.commit()
        request = PublishIn(
            taskId=task.id,
            platforms=["douyin"],
            title="发布活动成片",
        )
        jobs = await service.create_jobs(
            db,
            task.user_id,
            request,
        )
        duplicate = await service.create_jobs(db, task.user_id, request)
        changed = await service.create_jobs(
            db,
            task.user_id,
            PublishIn(
                taskId=task.id,
                platforms=["douyin"],
                title="更新后的发布标题",
                topics=["新版话题"],
            ),
        )
        stored = await db.get(PublishJob, jobs[0].id)

    assert duplicate[0].id == jobs[0].id
    assert changed[0].id == jobs[0].id
    assert stored is not None
    assert stored.title == "更新后的发布标题"
    assert json.loads(stored.topics_json) == ["新版话题"]
    assert stored.render_version == 2
    assert stored.render_version_id
    assert stored.video_key == "compose/v2.mp4"
    assert stored.cover_key == "compose/v2.jpg"


async def test_manual_publish_backfills_legacy_job_with_bootstrapped_render_version(monkeypatch) -> None:
    from app.modules.pipeline.models import PipelineTask
    from app.modules.publish import repository as publish_repo
    from app.modules.publish import service
    from app.modules.publish.schemas import PublishIn

    monkeypatch.setattr(
        service,
        "settings",
        SimpleNamespace(app_env="test", publish_verified_platforms=""),
    )
    async with SessionLocal() as db:
        task = PipelineTask(
            user_id="legacy-render-publish-user",
            ip_id="ip-legacy",
            title="存量发布任务",
            status="done",
            artifacts_json=json.dumps(
                {
                    "final_video_key": "compose/legacy.mp4",
                    "cover_key": "compose/legacy.jpg",
                    "quality": {"passed": True},
                }
            ),
        )
        db.add(task)
        await db.commit()
        legacy = await publish_repo.create_job(
            db,
            user_id=task.user_id,
            task_id=task.id,
            platform="douyin",
            title="存量发布任务",
            topics_json="[]",
            video_key="compose/legacy.mp4",
            cover_key="compose/legacy.jpg",
            status="export_ready",
        )
        jobs = await service.create_jobs(
            db,
            task.user_id,
            PublishIn(
                taskId=task.id,
                platforms=["douyin"],
                title="存量发布任务",
            ),
        )
        stored = await publish_repo.get_job(db, legacy.id, task.user_id)

    assert jobs[0].id == legacy.id
    assert stored is not None
    assert stored.render_version == 1
    assert stored.render_version_id


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
