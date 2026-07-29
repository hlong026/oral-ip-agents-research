"""Publication finalization P0: draft, immutable revision, render and publish contract."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.db import SessionLocal, init_models
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.billing.models import PriceQuote
from app.modules.billing.service import grant_points
from app.modules.pipeline.models import PipelineRenderVersion, PipelineTask, PublicationRevision
from app.modules.pipeline.schemas import PublicationContentIn, PublicationDraftPutIn, PublicationFinalizeIn


@pytest_asyncio.fixture(autouse=True)
async def _database() -> None:
    await init_models()


def _content(title: str = "定稿标题") -> PublicationContentIn:
    return PublicationContentIn(
        title=title,
        topics=["经营", "获客"],
        subtitles={
            "enabled": True,
            "source": "manual",
            "segments": [{"id": "s1", "startMs": 0, "endMs": 900, "text": "你好世界"}],
            "style": {
                "fontFamily": "Noto Sans CJK SC",
                "fontSize": 48,
                "color": "#FFFFFF",
                "stroke": 3,
                "xPercent": 50,
                "yPercent": 82,
            },
        },
        cover={"selectedFrameMs": 1500, "template": "bold-bottom"},
    )


def test_publication_content_rejects_whitespace_only_title() -> None:
    with pytest.raises(ValidationError):
        _content("   ")


async def _task_with_quote(*, clean: bool = True, burned: bool = False) -> tuple[str, str, str]:
    user_id = uuid.uuid4().hex
    quote_id = f"quote_{uuid.uuid4().hex}"
    async with SessionLocal() as db:
        db.add(
            User(
                id=user_id,
                phone=f"139{uuid.uuid4().hex[:8]}",
                password_hash=hash_password("Test@12345"),
                nickname="publication-p0",
                role="user",
            )
        )
        await db.commit()
        await grant_points(
            db,
            user_id,
            30,
            source_type="manual",
            source_id=f"pub-{uuid.uuid4().hex}",
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        db.add(
            PriceQuote(
                id=quote_id,
                user_id=user_id,
                catalog_version_id="test-catalog",
                price_version="test-v1",
                items_json=json.dumps(
                    [{"module": "hd_export", "name": "高清导出", "quantity": 1, "unit": "per_action", "points": 3}],
                    ensure_ascii=False,
                ),
                estimated_points=3,
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
        )
        artifacts = {
            "script": "这是口播文案",
            "avatar_video_key": "avatar/source.mp4",
            "audio_key": "tts/source.mp3",
            "tts_words": [{"word": "你", "start": 0.0, "end": 0.2}, {"word": "好", "start": 0.2, "end": 0.4}],
            "final_video_key": "compose/active.mp4",
            "cover_key": "compose/active.jpg",
            "quality": {"passed": True},
        }
        if clean:
            artifacts["clean_video_key"] = "compose/clean.mp4"
        if burned:
            artifacts["subtitle_enabled"] = True
        task = PipelineTask(
            user_id=user_id,
            ip_id="ip-p0",
            title="初始标题",
            script_text="这是口播文案",
            status="done",
            artifacts_json=json.dumps(artifacts, ensure_ascii=False),
        )
        db.add(task)
        await db.commit()
        return task.id, user_id, quote_id


async def test_publication_draft_initializes_and_cas_saves() -> None:
    from app.modules.pipeline import service

    task_id, user_id, _quote_id = await _task_with_quote()
    async with SessionLocal() as db:
        draft = await service.get_publication_draft(db, task_id, user_id)
        saved = await service.put_publication_draft(
            db,
            task_id,
            user_id,
            PublicationDraftPutIn(draftRevision=draft.draftRevision, content=_content("新标题")),
        )
        with pytest.raises(HTTPException) as exc:
            await service.put_publication_draft(
                db,
                task_id,
                user_id,
                PublicationDraftPutIn(draftRevision=draft.draftRevision, content=_content("过期保存")),
            )

    assert draft.revision == 1
    assert draft.content.schemaVersion == 1
    assert saved.draftRevision == draft.draftRevision + 1
    assert saved.content.title == "新标题"
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "PUBLICATION_DRAFT_CONFLICT"


async def test_publication_draft_requires_completed_pipeline() -> None:
    from app.modules.pipeline import service

    task_id, user_id, _quote_id = await _task_with_quote()
    async with SessionLocal() as db:
        task = await db.get(PipelineTask, task_id)
        task.status = "running"
        await db.commit()

        with pytest.raises(HTTPException) as exc:
            await service.get_publication_draft(db, task_id, user_id)

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "TASK_NOT_READY"


def test_compose_retry_clears_clean_master_and_cover_candidate_cache() -> None:
    from app.modules.pipeline.service import _clear_artifacts_from

    task = PipelineTask(
        user_id="user-clear",
        ip_id="ip-clear",
        title="clear",
        artifacts_json=json.dumps(
            {
                "clean_video_key": "compose/clean.mp4",
                "subtitle_enabled": False,
                "cover_candidates": [{"timestampMs": 300, "imageKey": "cover/300.jpg"}],
                "final_video_key": "compose/final.mp4",
                "cover_key": "compose/cover.jpg",
            }
        ),
    )

    _clear_artifacts_from(task, "compose")

    artifacts = json.loads(task.artifacts_json)
    assert "clean_video_key" not in artifacts
    assert "subtitle_enabled" not in artifacts
    assert "cover_candidates" not in artifacts


async def test_metadata_suggestions_fallback_and_cover_candidates(monkeypatch) -> None:
    from app.modules.pipeline import service

    task_id, user_id, _quote_id = await _task_with_quote()
    extracted: list[int] = []

    async def fake_extract(_clean_key: str, timestamp_ms: int) -> str:
        extracted.append(timestamp_ms)
        return f"cover-candidates/{timestamp_ms}.jpg"

    monkeypatch.setattr(service, "_extract_cover_candidate_frame", fake_extract)
    async with SessionLocal() as db:
        suggestions = await service.metadata_suggestions(db, task_id, user_id)
        candidates = await service.cover_candidates(db, task_id, user_id)

    assert len(suggestions.titles) == 3
    assert 5 <= len(suggestions.tags) <= 8
    assert [item.timestampMs for item in candidates] == [300, 1500, 2700]
    assert all(item.imageUrl for item in candidates)
    assert extracted == [300, 1500, 2700]


async def test_cover_candidates_reject_legacy_burned_video_without_clean_master(monkeypatch) -> None:
    from app.modules.pipeline import service

    task_id, user_id, _quote_id = await _task_with_quote(clean=False, burned=True)

    async def forbidden_extract(_clean_key: str, _timestamp_ms: int) -> str:
        raise AssertionError("烧字幕旧成片不得用于抽取封面候选")

    monkeypatch.setattr(service, "_extract_cover_candidate_frame", forbidden_extract)
    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as exc:
            await service.cover_candidates(db, task_id, user_id)

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "CLEAN_MASTER_REQUIRED"


async def test_finalize_is_idempotent_and_creates_render(monkeypatch) -> None:
    from app.modules.pipeline import service

    task_id, user_id, quote_id = await _task_with_quote()
    scheduled: list[str] = []
    monkeypatch.setattr(service, "schedule_render", lambda render_id: scheduled.append(render_id) or "render-msg")
    async with SessionLocal() as db:
        draft = await service.get_publication_draft(db, task_id, user_id)
        first = await service.finalize_publication(
            db,
            task_id,
            user_id,
            PublicationFinalizeIn(
                quoteId=quote_id,
                idempotencyKey=f"pub-{uuid.uuid4().hex}",
                draftRevision=draft.draftRevision,
            ),
        )
        second = await service.finalize_publication(
            db,
            task_id,
            user_id,
            PublicationFinalizeIn(
                quoteId=quote_id,
                idempotencyKey=first.renderVersionId or "missing",
                draftRevision=draft.draftRevision,
            ),
        )
        render = await db.get(PipelineRenderVersion, first.renderVersionId)

    assert first.id == second.id
    assert first.status == "rendering"
    assert render is not None
    assert render.status == "pending"
    assert json.loads(render.config_json)["publication_revision_id"] == first.id
    assert scheduled == [render.id]


async def test_render_success_finalizes_revision_and_supersedes_old(monkeypatch) -> None:
    from app.modules.billing import service as billing_service
    from app.modules.pipeline import render as render_module

    task_id, user_id, _quote_id = await _task_with_quote()
    async with SessionLocal() as db:
        old = PublicationRevision(user_id=user_id, task_id=task_id, revision=1, status="finalized", draft_revision=1)
        db.add(old)
        new = PublicationRevision(
            user_id=user_id,
            task_id=task_id,
            revision=2,
            status="rendering",
            draft_revision=1,
            content_spec_json=_content("新版").model_dump_json(),
        )
        db.add(new)
        rv = PipelineRenderVersion(
            task_id=task_id,
            user_id=user_id,
            version=2,
            base_version=1,
            status="rendered",
            config_json=json.dumps({"publication_revision_id": new.id, "content": _content("新版").model_dump()}),
            reservation_id="",
            idempotency_key=f"render-{uuid.uuid4().hex}",
            video_key="compose/finalized.mp4",
            cover_key="compose/finalized.jpg",
            quality_json='{"passed": true}',
        )
        db.add(rv)
        await db.flush()
        new.render_version_id = rv.id
        await db.commit()
    async def fake_settle(*_args, **_kwargs):
        return 1

    monkeypatch.setattr(billing_service, "settle_reservation", fake_settle)

    async with SessionLocal() as db:
        await render_module._settle_and_activate(db, rv.id)
        refreshed_old = await db.get(PublicationRevision, old.id)
        refreshed_new = await db.get(PublicationRevision, new.id)

    assert refreshed_new.status == "finalized"
    assert refreshed_old.status == "superseded"


async def test_render_failure_returns_revision_to_draft() -> None:
    from app.modules.pipeline.render import _fail_render

    task_id, user_id, _quote_id = await _task_with_quote()
    async with SessionLocal() as db:
        rev = PublicationRevision(user_id=user_id, task_id=task_id, revision=1, status="rendering", draft_revision=2)
        db.add(rev)
        rv = PipelineRenderVersion(
            task_id=task_id,
            user_id=user_id,
            version=2,
            base_version=1,
            status="running",
            config_json=json.dumps({"publication_revision_id": rev.id}),
            idempotency_key=f"render-{uuid.uuid4().hex}",
        )
        db.add(rv)
        await db.flush()
        rev.render_version_id = rv.id
        await db.commit()
        await _fail_render(db, rv, "渲染失败")
        refreshed = await db.get(PublicationRevision, rev.id)

    assert refreshed.status == "draft"
    assert refreshed.last_error == "渲染失败"


async def test_finalize_blocks_legacy_burned_subtitles_without_clean_master() -> None:
    from app.modules.pipeline import service

    task_id, user_id, quote_id = await _task_with_quote(clean=False, burned=True)
    async with SessionLocal() as db:
        draft = await service.get_publication_draft(db, task_id, user_id)
        with pytest.raises(HTTPException) as exc:
            await service.finalize_publication(
                db,
                task_id,
                user_id,
                PublicationFinalizeIn(
                    quoteId=quote_id,
                    idempotencyKey=f"pub-{uuid.uuid4().hex}",
                    draftRevision=draft.draftRevision,
                ),
            )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "CLEAN_MASTER_REQUIRED"


async def test_publish_uses_finalized_immutable_revision_and_account_selection(monkeypatch) -> None:
    from app.modules.publish import repository as publish_repo
    from app.modules.publish import service as publish_service

    monkeypatch.setattr(
        publish_service,
        "settings",
        SimpleNamespace(app_env="test", publish_verified_platforms="douyin"),
    )
    monkeypatch.setattr(publish_service, "_schedule_job", lambda *_args, **_kwargs: "queued-msg")
    task_id, user_id, _quote_id = await _task_with_quote()
    async with SessionLocal() as db:
        render = PipelineRenderVersion(
            task_id=task_id,
            user_id=user_id,
            version=2,
            base_version=1,
            status="done",
            idempotency_key=f"render-{uuid.uuid4().hex}",
            video_key="compose/revision.mp4",
            cover_key="compose/revision.jpg",
            quality_json='{"passed": true}',
            is_active=True,
        )
        db.add(render)
        await db.flush()
        revision = PublicationRevision(
            user_id=user_id,
            task_id=task_id,
            revision=1,
            status="finalized",
            render_version_id=render.id,
            content_spec_json=_content("不可变标题").model_dump_json(),
            draft_revision=2,
        )
        db.add(revision)
        await publish_repo.create_account(
            db, user_id=user_id, platform="douyin", nickname="A", session_json="{}", status="active"
        )
        second = await publish_repo.create_account(
            db, user_id=user_id, platform="douyin", nickname="B", session_json="{}", status="active"
        )
        with pytest.raises(HTTPException) as exc:
            await publish_service.create_jobs(
                db,
                user_id,
                publish_service.PublishIn(publicationRevisionId=revision.id, platforms=["douyin"], accountIds={}),
            )
        jobs = await publish_service.create_jobs(
            db,
            user_id,
            publish_service.PublishIn(
                publicationRevisionId=revision.id,
                platforms=["douyin"],
                accountIds={"douyin": second.id},
            ),
        )

    assert exc.value.detail["code"] == "ACCOUNT_ID_REQUIRED"
    assert jobs[0].publicationRevisionId == revision.id
    assert jobs[0].accountId == second.id
    assert jobs[0].title == "不可变标题"


async def test_publish_rejects_legacy_request_without_finalized_revision() -> None:
    from app.modules.publish import service as publish_service

    with pytest.raises(HTTPException) as exc:
        async with SessionLocal() as db:
            await publish_service.create_jobs(
                db,
                "legacy-user",
                publish_service.PublishIn(
                    taskId="legacy-task",
                    platforms=["douyin"],
                    title="绕过定稿的标题",
                ),
            )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "PUBLICATION_REVISION_REQUIRED"


async def test_publish_does_not_reuse_started_job_for_another_account(monkeypatch) -> None:
    from app.modules.publish import repository as publish_repo
    from app.modules.publish import service as publish_service

    monkeypatch.setattr(
        publish_service,
        "settings",
        SimpleNamespace(app_env="test", publish_verified_platforms="douyin"),
    )
    monkeypatch.setattr(publish_service, "_schedule_job", lambda *_args, **_kwargs: "queued-msg")
    async with SessionLocal() as db:
        first_account = await publish_repo.create_account(
            db, user_id="account-reuse-user", platform="douyin", nickname="A", session_json="{}", status="active"
        )
        second_account = await publish_repo.create_account(
            db, user_id="account-reuse-user", platform="douyin", nickname="B", session_json="{}", status="active"
        )
        await publish_service.publish_task_video(
            db,
            "account-reuse-user",
            "account-reuse-task",
            ["douyin"],
            "账号不可静默替换",
            "compose/account.mp4",
            "compose/account.jpg",
            render_version_id="render-account",
            publication_revision_id="revision-account",
            account_ids={"douyin": first_account.id},
        )

        with pytest.raises(HTTPException) as exc:
            await publish_service.publish_task_video(
                db,
                "account-reuse-user",
                "account-reuse-task",
                ["douyin"],
                "账号不可静默替换",
                "compose/account.mp4",
                "compose/account.jpg",
                render_version_id="render-account",
                publication_revision_id="revision-account",
                account_ids={"douyin": second_account.id},
            )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "PUBLISH_ALREADY_STARTED"


async def test_initial_compose_is_clean_and_segments_map_to_ass_style(monkeypatch) -> None:
    from app.modules.pipeline import engine
    from app.providers.base import ComposeResult
    from app.providers.real import _build_ass

    captured = {}

    async def fake_run(_module, _chain, _step, inp, **_kwargs):
        captured["inp"] = inp
        result = ComposeResult(
            video_key="compose/clean.mp4",
            cover_key="compose/cover.jpg",
            duration=1,
            quality={"passed": True},
        )
        return result, "ffmpeg-local"

    monkeypatch.setattr(engine.registry, "run_with_fallback", fake_run)
    task = SimpleNamespace(id="task-clean", user_id="user-clean", title="clean", randomize=False, trace_id="trace")
    out = await engine._compose_with_ctx(
        task,
        {
            "avatar_video_key": "avatar/a.mp4",
            "audio_key": "tts/a.mp3",
            "tts_words": [{"word": "你", "start": 0.0, "end": 0.2}],
        },
    )
    ass = _build_ass(
        engine._segments_to_words([{"id": "s1", "startMs": 100, "endMs": 900, "text": "精准字幕"}]),
        1080,
        1920,
        {"fontFamily": "PingFang SC", "fontSize": 52, "color": "#22D3EE", "stroke": 4, "xPercent": 50, "yPercent": 80},
        exact=True,
    )

    assert captured["inp"].subtitle_words == []
    assert out["clean_video_key"] == "compose/clean.mp4"
    assert "PingFang SC" in ass
    assert "Dialogue: 0,0:00:00.10,0:00:00.90" in ass


async def test_pipeline_publish_reads_finalized_revision_and_linked_render(monkeypatch) -> None:
    from app.modules.pipeline import engine
    from app.modules.publish import service as publish_service

    task_id, user_id, _quote_id = await _task_with_quote()
    captured: dict[str, object] = {}

    async def fake_publish(_db, user_id, task_id, platforms, **kwargs):
        captured.update(user_id=user_id, task_id=task_id, platforms=platforms, **kwargs)
        return ["job-finalized"]

    monkeypatch.setattr(publish_service, "publish_task_video", fake_publish)
    async with SessionLocal() as db:
        task = await db.get(PipelineTask, task_id)
        task.platforms_json = '["douyin"]'
        render = PipelineRenderVersion(
            task_id=task_id,
            user_id=user_id,
            version=3,
            base_version=2,
            status="done",
            idempotency_key=f"render-{uuid.uuid4().hex}",
            video_key="compose/revision-only.mp4",
            cover_key="compose/revision-only.jpg",
            quality_json='{"passed": true}',
        )
        db.add(render)
        await db.flush()
        revision = PublicationRevision(
            user_id=user_id,
            task_id=task_id,
            revision=1,
            status="finalized",
            render_version_id=render.id,
            content_spec_json=_content("Revision 标题").model_dump_json(),
            draft_revision=2,
        )
        db.add(revision)
        await db.commit()

    result = await engine.step_publish(
        task,
        {
            "script": "ctx title should not be used",
            "final_video_key": "compose/ctx.mp4",
            "cover_key": "compose/ctx.jpg",
            "quality": {"passed": True},
        },
    )

    assert result == {"publish_job_ids": ["job-finalized"]}
    assert captured["title"] == "Revision 标题"
    assert captured["topics"] == ["经营", "获客"]
    assert captured["video_key"] == "compose/revision-only.mp4"
    assert captured["cover_key"] == "compose/revision-only.jpg"
    assert captured["publication_revision_id"] == revision.id
