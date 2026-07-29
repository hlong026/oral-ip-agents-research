"""用户资产绑定和流水线引用必须同时满足归属与就绪状态。"""

import json

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.core.db import SessionLocal
from app.modules.avatar.models import Avatar
from app.modules.ipasset.models import Persona
from app.modules.ipasset.schemas import PersonaUpdate
from app.modules.pipeline.models import PipelineRenderVersion, PipelineTask, PublicationRevision
from app.modules.pipeline.schemas import PublicationContentIn
from app.modules.voice.models import Voice


async def test_persona_rejects_cross_user_and_unready_assets_without_partial_update(
    client: AsyncClient,
) -> None:
    from app.modules.ipasset.service import update_persona

    owner_id = "asset-owner"
    other_id = "asset-other"
    async with SessionLocal() as db:
        persona = Persona(user_id=owner_id, name="资产归属测试")
        foreign_voice = Voice(user_id=other_id, name="他人声音", status="ready", provider_voice_id="remote")
        training_avatar = Avatar(user_id=owner_id, name="训练中数字人", status="training")
        db.add_all([persona, foreign_voice, training_avatar])
        await db.commit()

        with pytest.raises(HTTPException) as foreign_error:
            await update_persona(
                db,
                owner_id,
                persona.id,
                PersonaUpdate(name="不应保存", voiceId=foreign_voice.id),
            )
        assert foreign_error.value.status_code == 404
        await db.refresh(persona)
        assert persona.name == "资产归属测试"
        assert persona.voice_id is None

        with pytest.raises(HTTPException) as unready_error:
            await update_persona(
                db,
                owner_id,
                persona.id,
                PersonaUpdate(avatarId=training_avatar.id),
            )
        assert unready_error.value.status_code == 409
        await db.refresh(persona)
        assert persona.avatar_id is None


async def test_persona_accepts_owned_ready_assets_and_avatar_delete_unbinds(
    client: AsyncClient,
) -> None:
    from app.modules.avatar.service import delete_avatar
    from app.modules.ipasset.service import update_persona

    user_id = "asset-ready-owner"
    async with SessionLocal() as db:
        persona = Persona(user_id=user_id, name="可绑定人设")
        voice = Voice(user_id=user_id, name="已就绪声音", status="ready", provider_voice_id="voice-remote")
        avatar = Avatar(user_id=user_id, name="已就绪数字人", status="ready", provider_avatar_id="avatar-remote")
        db.add_all([persona, voice, avatar])
        await db.commit()

        updated = await update_persona(
            db,
            user_id,
            persona.id,
            PersonaUpdate(voiceId=voice.id, avatarId=avatar.id),
        )
        assert updated.voiceId == voice.id
        assert updated.avatarId == avatar.id

        await delete_avatar(db, user_id, avatar.id)
        await db.refresh(persona)
        assert persona.voice_id == voice.id
        assert persona.avatar_id is None


async def test_pipeline_asset_validation_rejects_provider_id_injection(
    client: AsyncClient,
) -> None:
    from app.modules.pipeline.service import validate_ready_assets

    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as error:
            await validate_ready_assets(
                db,
                "pipeline-owner",
                persona_id="missing-persona",
                voice_id="raw-provider-voice-id",
                avatar_id="raw-provider-avatar-id",
            )

    assert error.value.status_code == 404
    assert error.value.detail["code"] == "PERSONA_NOT_FOUND"


async def test_pipeline_resolves_owned_ready_assets_from_persona_defaults(client: AsyncClient) -> None:
    from app.modules.pipeline.service import validate_ready_assets

    user_id = "pipeline-default-owner"
    async with SessionLocal() as db:
        voice = Voice(user_id=user_id, name="默认声音", status="ready", provider_voice_id="remote-voice")
        avatar = Avatar(user_id=user_id, name="默认数字人", status="ready", provider_avatar_id="remote-avatar")
        db.add_all([voice, avatar])
        await db.flush()
        persona = Persona(
            user_id=user_id,
            name="默认资产人设",
            voice_id=voice.id,
            avatar_id=avatar.id,
        )
        db.add(persona)
        await db.commit()

        resolved = await validate_ready_assets(
            db,
            user_id,
            persona_id=persona.id,
            voice_id=None,
            avatar_id=None,
        )

    assert resolved == (voice.id, avatar.id)


async def test_voice_step_never_uses_unknown_local_id_as_provider_id(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.pipeline import engine

    async def forbidden_provider_call(*_args, **_kwargs):
        raise AssertionError("未知本地声音 ID 不得下发给 Provider")

    monkeypatch.setattr(engine.registry, "run_with_fallback", forbidden_provider_call)
    task = PipelineTask(
        id="pipeline-unknown-voice",
        user_id="pipeline-owner",
        script_text="测试文案",
        voice_id="raw-provider-voice-id",
    )

    with pytest.raises(RuntimeError, match="声音不存在"):
        await engine.step_voice(task, {})


async def test_publish_jobs_only_use_server_owned_pipeline_artifacts(
    client: AsyncClient,
) -> None:
    from app.modules.publish.repository import get_job
    from app.modules.publish.schemas import PublishIn
    from app.modules.publish.service import create_jobs

    owner_id = "publish-asset-owner"
    task = PipelineTask(
        user_id=owner_id,
        ip_id="publish-persona",
        title="归属校验成片",
        status="done",
        artifacts_json=json.dumps(
            {
                "final_video_key": "compose/owned.mp4",
                "cover_key": "compose/owned.jpg",
                "quality": {"passed": True},
            }
        ),
    )
    async with SessionLocal() as db:
        db.add(task)
        await db.flush()
        render = PipelineRenderVersion(
            task_id=task.id,
            user_id=owner_id,
            version=2,
            base_version=1,
            status="done",
            idempotency_key=f"ownership:{task.id}:2",
            video_key="compose/owned.mp4",
            cover_key="compose/owned.jpg",
            quality_json='{"passed": true}',
            is_active=True,
        )
        db.add(render)
        await db.flush()
        revision = PublicationRevision(
            user_id=owner_id,
            task_id=task.id,
            revision=1,
            status="finalized",
            render_version_id=render.id,
            content_spec_json=PublicationContentIn(
                title="归属校验成片",
                subtitles={"enabled": False},
            ).model_dump_json(),
        )
        db.add(revision)
        await db.commit()

        with pytest.raises(HTTPException) as cross_user_error:
            await create_jobs(
                db,
                "publish-other-user",
                PublishIn(
                    publicationRevisionId=revision.id,
                    platforms=["shipinhao"],
                ),
            )
        assert cross_user_error.value.status_code == 409
        assert cross_user_error.value.detail["code"] == "PUBLICATION_REVISION_NOT_FINALIZED"

        jobs = await create_jobs(
            db,
            owner_id,
            PublishIn(
                publicationRevisionId=revision.id,
                platforms=["shipinhao"],
                title="客户端伪造标题",
                videoKey="compose/other-users-video.mp4",
                coverKey="compose/other-users-cover.jpg",
            ),
        )
        stored = await get_job(db, jobs[0].id, owner_id)
        assert stored is not None
        assert stored.title == "归属校验成片"
        assert stored.video_key == "compose/owned.mp4"
        assert stored.cover_key == "compose/owned.jpg"
