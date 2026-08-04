"""独立重合成 Worker：先渲染并结算，最后原子切换活动版本。"""

import json

from sqlalchemy import update

from app.core.db import SessionLocal
from app.core.logging import get_logger
from app.core.white_label import public_error_message
from app.modules.billing.models import CreditReservation
from app.providers.base import is_mock_provider

from . import repository as repo
from .engine import _compose_with_ctx
from .models import PipelineRenderVersion, PublicationRevision
from .schemas import EditConfigIn

logger = get_logger("oral.pipeline.render")


def _apply_config(artifacts: dict, config: EditConfigIn) -> dict:
    updated = dict(artifacts)
    updated["subtitle_enabled"] = config.subtitleEnabled
    updated["subtitle_style"] = config.subtitleStyle.model_dump()
    updated["bgm_mode"] = config.bgmMode
    updated["bgm_volume"] = config.bgmVolume / 100
    updated["cover_template"] = config.coverTemplate
    return updated


def _apply_raw_render_config(artifacts: dict, raw_config: dict) -> dict:
    if raw_config.get("publication_revision_id"):
        updated = dict(artifacts)
        updated["publication_revision_id"] = raw_config["publication_revision_id"]
        updated["content"] = raw_config.get("content") or {}
        updated["clean_video_key"] = raw_config.get("clean_video_key") or artifacts.get("clean_video_key") or ""
        updated["avatar_video_key"] = updated["clean_video_key"] or artifacts.get("avatar_video_key") or ""
        updated["subtitle_enabled"] = bool(raw_config.get("subtitleEnabled"))
        updated["subtitle_style"] = raw_config.get("subtitleStyle") or {}
        updated["cover_template"] = raw_config.get("coverTemplate") or "bold-bottom"
        return updated
    return _apply_config(artifacts, EditConfigIn.model_validate(raw_config))


async def run_render_version(render_id: str) -> None:
    """执行一个渲染版本；失败或取消绝不覆盖当前活动成片。"""
    async with SessionLocal() as db:
        render = await repo.get_render(db, render_id)
        if render is None:
            return
        if render.status == "pending":
            render = await repo.claim_render(db, render_id)
        elif render.status != "rendered":
            return
        if render is None:
            return
        task = await repo.get(db, render.task_id, render.user_id)
        if task is None:
            await _fail_render(db, render, "原任务不存在")
            return

        if render.status != "rendered":
            raw_config = json.loads(render.config_json or "{}")
            artifacts = _apply_raw_render_config(json.loads(task.artifacts_json or "{}"), raw_config)
            try:
                result = await _compose_with_ctx(task, artifacts)
                # 真实合成失败降级到 mock 时，产物为占位文件，会被质检误判为“质量不过”；
                # 此处直接报失败并提示真实可能原因（FFmpeg/字幕环境），避免误导“稍后重试”。
                if result.get("degraded_mock") or is_mock_provider(str(result.get("provider") or "")):
                    raise RuntimeError("真实合成失败并降级为演示数据，请核查 FFmpeg 环境/字幕配置后重试")
                quality = result.get("quality")
                if not isinstance(quality, dict) or not quality.get("passed"):
                    raise RuntimeError("成片质量检查未通过")
                if not str(result.get("final_video_key") or ""):
                    raise RuntimeError("成片文件缺失")
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "pipeline_render_failed",
                    render_id=render.id,
                    task_id=task.id,
                    user_id=render.user_id,
                )
                await _fail_render(db, render, public_error_message(exc))
                return

            await db.refresh(render)
            if render.status == "canceled":
                return
            render.video_key = str(result.get("final_video_key") or "")
            render.cover_key = str(result.get("cover_key") or "")
            render.quality_json = json.dumps(quality, ensure_ascii=False)
            render.status = "rendered"
            render.error = ""
            await db.commit()

        await _settle_and_activate(db, render.id)


async def _settle_and_activate(db, render_id: str) -> None:
    render = await repo.get_render(db, render_id)
    if render is None or render.status != "rendered":
        return
    task = await repo.get(db, render.task_id, render.user_id)
    if task is None:
        await _fail_render(db, render, "原任务不存在")
        return

    from app.modules.billing.service import (
        recover_reservation_after_failure,
        settle_reservation,
    )

    settled = await settle_reservation(
        db,
        render.reservation_id,
        render.id,
        step="hd_export",
    )
    if settled <= 0:
        recovered = await recover_reservation_after_failure(
            db,
            render.reservation_id,
            render.user_id,
        )
        if recovered is None or recovered.status != "settled":
            current = await repo.get_render(db, render.id)
            if current is not None:
                await _fail_render(db, current, "积分结算失败")
            return

    render = await repo.get_render(db, render_id)
    task = await repo.get(db, render.task_id, render.user_id) if render else None
    if render is None or task is None or render.status != "rendered":
        return
    raw_config = json.loads(render.config_json or "{}")
    # 同步顶层键（subtitle_enabled/subtitle_style/bgm/cover_template）：
    # 主流水线重跑 compose 步只读顶层键，需沿用激活版剪辑配置而非仅存 edit_config
    config = EditConfigIn.model_validate(raw_config)
    artifacts = _apply_raw_render_config(json.loads(task.artifacts_json or "{}"), raw_config)
    artifacts.update(
        {
            "final_video_key": render.video_key,
            "cover_key": render.cover_key,
            "quality": json.loads(render.quality_json or "{}"),
            "render_version": render.version,
            "render_version_id": render.id,
            "edit_config": config.model_dump(),
        }
    )
    await db.execute(
        update(PipelineRenderVersion)
        .where(
            PipelineRenderVersion.task_id == task.id,
            PipelineRenderVersion.is_active.is_(True),
        )
        .values(is_active=False)
    )
    render.is_active = True
    render.status = "done"
    render.error = ""
    task.active_render_version = render.version
    task.artifacts_json = json.dumps(artifacts, ensure_ascii=False)
    revision = await _linked_revision(db, render, raw_config)
    if revision is not None:
        await db.execute(
            update(PublicationRevision)
            .where(
                PublicationRevision.task_id == task.id,
                PublicationRevision.user_id == render.user_id,
                PublicationRevision.status == "finalized",
                PublicationRevision.id != revision.id,
            )
            .values(status="superseded")
        )
        revision.status = "finalized"
        revision.last_error = ""
        from datetime import UTC, datetime

        revision.finalized_at = datetime.now(UTC)
    await db.commit()
    logger.info(
        "pipeline_render_activated",
        render_id=render.id,
        task_id=task.id,
        version=render.version,
        user_id=render.user_id,
    )


async def _fail_render(db, render: PipelineRenderVersion, message: str) -> None:
    from app.modules.billing.service import recover_reservation_after_failure

    render_id = render.id
    reservation_id = render.reservation_id
    user_id = render.user_id
    if reservation_id:
        reservation = await db.get(CreditReservation, reservation_id)
        if reservation is not None and reservation.status == "reserved":
            await recover_reservation_after_failure(db, reservation_id, user_id)
    current = await repo.get_render(db, render_id)
    if current is None or current.status == "canceled":
        return
    current.status = "failed"
    current.error = message[:500]
    current.queue_message_id = ""
    raw_config = json.loads(current.config_json or "{}")
    revision = await _linked_revision(db, current, raw_config)
    if revision is not None:
        revision.status = "draft"
        revision.last_error = message[:500]
    await db.commit()


async def _linked_revision(db, render: PipelineRenderVersion, raw_config: dict) -> PublicationRevision | None:
    from sqlalchemy import select

    revision_id = str(raw_config.get("publication_revision_id") or "")
    revision = await db.get(PublicationRevision, revision_id) if revision_id else None
    if revision is None:
        revision = (
            await db.execute(
                select(PublicationRevision).where(
                    PublicationRevision.render_version_id == render.id,
                    PublicationRevision.user_id == render.user_id,
                )
            )
        ).scalar_one_or_none()
    if revision is None or revision.user_id != render.user_id or revision.render_version_id != render.id:
        return None
    return revision
