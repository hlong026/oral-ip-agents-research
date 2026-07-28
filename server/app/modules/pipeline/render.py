"""独立重合成 Worker：先渲染并结算，最后原子切换活动版本。"""

import json

from sqlalchemy import update

from app.core.db import SessionLocal
from app.core.logging import get_logger
from app.core.white_label import public_error_message
from app.modules.billing.models import CreditReservation

from . import repository as repo
from .engine import _compose_with_ctx
from .models import PipelineRenderVersion
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
            config = EditConfigIn.model_validate(json.loads(render.config_json or "{}"))
            artifacts = _apply_config(json.loads(task.artifacts_json or "{}"), config)
            try:
                result = await _compose_with_ctx(task, artifacts)
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
    config = EditConfigIn.model_validate(json.loads(render.config_json or "{}"))
    # 同步顶层键（subtitle_enabled/subtitle_style/bgm/cover_template）：
    # 主流水线重跑 compose 步只读顶层键，需沿用激活版剪辑配置而非仅存 edit_config
    artifacts = _apply_config(json.loads(task.artifacts_json or "{}"), config)
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
    await db.commit()
