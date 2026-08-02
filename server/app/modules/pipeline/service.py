"""pipeline 业务编排（F-405/406：批量扇出、单步重跑、manual 确认）
日志：任务生命周期（§10.6.8-B #1）
"""

import asyncio
import json
import re
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.storage import exists as storage_exists
from app.core.storage import signed_media_path
from app.core.white_label import public_metadata

from . import repository as repo
from .engine import schedule_run
from .models import STEP_ORDER, PipelineRenderVersion, PipelineTask, PublicationRevision
from .schemas import (
    CoverCandidateOut,
    CoverPreviewIn,
    CoverPreviewOut,
    CreatePipelineIn,
    EditConfigIn,
    MetadataSuggestionGroupOut,
    MetadataSuggestionsOut,
    PublicationContentIn,
    PublicationDraftPutIn,
    PublicationFinalizeIn,
    PublicationRevisionOut,
    PublicationSubtitlesIn,
    RecomposeIn,
    RenderVersionOut,
    StatsOut,
    StepStateOut,
    TaskOut,
    TaskPageOut,
)

logger = get_logger("oral.pipeline.service")
settings = get_settings()
_user_creation_locks: dict[str, asyncio.Lock] = {}
_render_creation_locks: dict[str, asyncio.Lock] = {}


def _default_steps() -> list[dict]:
    return [
        {
            "step": s,
            "status": "pending",
            "progress": 0,
            "message": "",
            "compute": "cloud",
            "provider": "",
            "quotaCost": 0.0,
            "artifacts": {},
            "startedAt": None,
            "finishedAt": None,
            "durationMs": None,
        }
        for s in STEP_ORDER
    ]


async def create(db: AsyncSession, user_id: str, inp: CreatePipelineIn) -> list[TaskOut]:
    """同进程用轻量锁补齐 SQLite；生产数据库再用用户行锁跨进程串行化。"""
    lock = _user_creation_locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        return await _create_serialized(db, user_id, inp)


async def _create_serialized(db: AsyncSession, user_id: str, inp: CreatePipelineIn) -> list[TaskOut]:
    """创建任务；count>1 时批量扇出共享 batch_id（F-406）"""
    from app.modules.auth import repository as auth_repo

    user = await auth_repo.get_by_id_for_update(db, user_id)
    plan_expires_at = user.plan_expires_at if user else None
    if plan_expires_at and plan_expires_at.tzinfo is None:
        plan_expires_at = plan_expires_at.replace(tzinfo=UTC)
    if not user or not plan_expires_at or plan_expires_at <= datetime.now(UTC):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"code": "SUBSCRIPTION_REQUIRED", "message": "套餐未开通或已到期，请先激活或续费"},
        )
    if settings.app_env != "dev" and not inp.quoteId:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "QUOTE_REQUIRED", "message": "任务报价缺失，请重新计算积分后提交"},
        )
    if not (inp.sourceUrl or inp.topic or inp.scriptText or inp.scriptId):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INPUT_REQUIRED", "message": "链接/选题/文案至少填一项"},
        )
    script_id, script_version, script_text = await resolve_script_snapshot(db, user_id, inp)
    voice_id, avatar_id = await validate_ready_assets(
        db,
        user_id,
        persona_id=inp.ipId,
        voice_id=inp.voiceId,
        avatar_id=inp.avatarId,
    )
    count = max(1, min(inp.count, 20))
    from app.modules.activation import repository as activation_repo
    from app.modules.catalog import repository as catalog_repo

    subscriptions = await activation_repo.get_user_subscriptions(db, user_id)
    current_subscription = next((item for item in subscriptions if item.duration_days > 0), None)
    if current_subscription and current_subscription.sku_version_id:
        plan = await catalog_repo.get_plan_version(db, current_subscription.sku_version_id)
        if plan:
            active_tasks = await repo.active_count(db, user_id)
            if active_tasks + count > plan.max_concurrency:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    detail={
                        "code": "PLAN_CONCURRENCY_EXCEEDED",
                        "message": f"当前套餐最多允许 {plan.max_concurrency} 个并发任务",
                    },
                )
    batch_id = uuid.uuid4().hex[:12] if count > 1 else None
    title_src = (inp.topic or script_text or inp.sourceUrl or "未命名任务")[:24]
    tasks: list[PipelineTask] = []
    reservation_ids: list[str] = []
    if inp.quoteId:
        from app.modules.billing.service import reserve_quote
        from app.modules.ipasset import repository as ipasset_repo

        persona = await ipasset_repo.get(db, inp.ipId, user_id)
        task_for_quote = inp.model_dump()
        task_for_quote.update(
            voiceId=voice_id,
            avatarId=avatar_id,
            scriptText=script_text,
            scriptId=script_id or None,
            scriptVersion=script_version or None,
        )
        task_for_quote["_targetDurationSeconds"] = max(
            1,
            persona.video_duration if persona else 60,
        )

        reservation_batch = await reserve_quote(
            db,
            user_id,
            inp.quoteId,
            count,
            task_for_quote,
            commit=False,
        )
        reservation_ids = [item.id for item in reservation_batch.items]
    try:
        for i in range(count):
            title = f"{title_src} ·{i + 1}" if count > 1 else title_src
            t = await repo.create(
                db,
                user_id=user_id,
                ip_id=inp.ipId,
                title=title,
                source_url=inp.sourceUrl or "",
                topic=inp.topic or "",
                script_text=script_text,
                script_id=script_id,
                script_version=script_version,
                voice_id=voice_id,
                avatar_id=avatar_id,
                platforms_json=json.dumps(inp.platforms, ensure_ascii=False),
                mode="manual" if inp.mode == "manual" else "auto",
                intensity=inp.intensity if inp.intensity in ("light", "structure", "theme") else "structure",
                randomize=inp.randomize or (count > 1),  # 批量默认开差异化随机化（C5）
                batch_id=batch_id,
                publish_at=inp.publishAt or "",
                steps_json=json.dumps(_default_steps(), ensure_ascii=False),
                reservation_id=reservation_ids[i] if reservation_ids else "",
            )
            if reservation_ids:
                from app.modules.billing.service import attach_reservation

                await attach_reservation(db, reservation_ids[i], user_id, t.id)
            tasks.append(t)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    for task in tasks:
        await _enqueue_created_task(db, task)
        await db.refresh(task)
    # 任务创建：记录 INFO（§10.6.8-B #1）
    logger.info(
        "task_created",
        user_id=user_id,
        task_id=tasks[0].id if tasks else "",
        mode=inp.mode or "auto",
        batch_size=count,
        source_type="url" if inp.sourceUrl else ("topic" if inp.topic else "script"),
    )
    return [to_out(t) for t in tasks]


async def _enqueue_created_task(db: AsyncSession, task: PipelineTask) -> bool:
    """投递新流水线；Broker 未接受时终止任务并恢复冻结积分。"""
    try:
        message_id = schedule_run(task.id)
    except Exception:  # noqa: BLE001
        logger.exception(
            "pipeline_enqueue_failed",
            task_id=task.id,
            user_id=task.user_id,
        )
        task.status = "failed"
        task.error = "任务队列暂不可用，积分已恢复，请稍后重试"
        task.queue_message_id = ""
        await repo.save(db, task)
        if task.reservation_id:
            from app.modules.billing.service import release_reservation

            await release_reservation(db, task.reservation_id, task.user_id)
        from app.modules.notify.service import notify_user

        await notify_user(
            db,
            task.user_id,
            "error",
            f"任务排队失败：{task.title}",
            "任务未开始执行，冻结积分已恢复，请稍后重新创建。",
        )
        return False
    try:
        await repo.record_queue_message(db, task.id, message_id)
    except Exception:  # noqa: BLE001
        # Broker 已接受消息，Worker 可能已经执行；保留 pending + 空回执供状态机认领。
        await db.rollback()
        logger.exception(
            "pipeline_queue_receipt_failed",
            task_id=task.id,
            user_id=task.user_id,
            message_id=message_id,
        )
    return True


async def resolve_script_snapshot(
    db: AsyncSession,
    user_id: str,
    inp: CreatePipelineIn,
) -> tuple[str, int, str]:
    """把文案版本解析为不可变快照，任务不再依赖前端临时状态。"""
    if not inp.scriptId:
        return "", 0, (inp.scriptText or "").strip()
    if inp.scriptVersion is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "SCRIPT_VERSION_REQUIRED", "message": "引用文案时必须指定版本"},
        )
    from app.modules.content import repository as content_repo

    script = await content_repo.get(db, inp.scriptId, user_id)
    version = await content_repo.get_version(db, inp.scriptId, user_id, inp.scriptVersion)
    if script is None or version is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "SCRIPT_VERSION_NOT_FOUND", "message": "文案版本不存在或不属于当前用户"},
        )
    version_text = version.text.strip()
    if inp.scriptText and inp.scriptText.strip() != version_text:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "SCRIPT_VERSION_MISMATCH", "message": "提交文案与所选版本不一致，请先保存终稿"},
        )
    return script.id, version.version, version_text


async def validate_ready_assets(
    db: AsyncSession,
    user_id: str,
    *,
    persona_id: str,
    voice_id: str | None,
    avatar_id: str | None,
) -> tuple[str, str]:
    """流水线只接受当前用户已就绪的本地资产 ID，禁止透传 Provider ID。"""
    from app.modules.avatar import repository as avatar_repo
    from app.modules.ipasset import repository as persona_repo
    from app.modules.voice import repository as voice_repo

    persona = await persona_repo.get(db, persona_id, user_id)
    if persona is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "PERSONA_NOT_FOUND", "message": "IP 档案不存在或不属于当前用户"},
        )
    effective_voice_id = voice_id or persona.voice_id
    effective_avatar_id = avatar_id or persona.avatar_id
    if not effective_voice_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "VOICE_REQUIRED", "message": "当前 IP 尚未绑定已就绪声音"},
        )
    if not effective_avatar_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "AVATAR_REQUIRED", "message": "当前 IP 尚未绑定已就绪数字人"},
        )
    voice = await voice_repo.get(db, effective_voice_id, user_id)
    if voice is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "VOICE_NOT_FOUND", "message": "声音不存在或不属于当前用户"},
        )
    if voice.status != "ready" or not voice.provider_voice_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "VOICE_NOT_READY", "message": "声音尚未完成克隆确认"},
        )
    avatar = await avatar_repo.get(db, effective_avatar_id, user_id)
    if avatar is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "AVATAR_NOT_FOUND", "message": "数字人不存在或不属于当前用户"},
        )
    if avatar.status != "ready" or not avatar.provider_avatar_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "AVATAR_NOT_READY", "message": "数字人尚未完成克隆"},
        )
    return effective_voice_id, effective_avatar_id


async def list_tasks(db: AsyncSession, user_id: str, status_: str | None, page: int, page_size: int) -> TaskPageOut:
    items, total = await repo.list_by_user(db, user_id, status_, page, page_size)
    return TaskPageOut(items=[to_out(t) for t in items], total=total, page=page, pageSize=page_size)


async def get_task(db: AsyncSession, task_id: str, user_id: str) -> TaskOut:
    t = await _must_get(db, task_id, user_id)
    return to_out(t)


async def recompose(
    db: AsyncSession,
    task_id: str,
    user_id: str,
    inp: RecomposeIn,
) -> RenderVersionOut:
    """为已完成任务创建一次独立、幂等、单独计费的重合成。"""
    lock = _render_creation_locks.setdefault(task_id, asyncio.Lock())
    async with lock:
        task = await repo.get_for_update(db, task_id, user_id)
        if task is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail={"code": "NOT_FOUND", "message": "任务不存在"},
            )
        existing = await repo.get_render_by_idempotency(db, user_id, inp.idempotencyKey)
        if existing is not None:
            expected_config = json.dumps(inp.config.model_dump(), ensure_ascii=False, sort_keys=True)
            # 旧版本 config_json 可能缺少后来新增的带默认值字段（如 subtitleEnabled），
            # 先过一遍模型归一化再比对，避免跨部署重试被误判为幂等键冲突；
            # 历史脏数据无法通过校验时视为无法证明一致，按冲突处理而非冒泡 500
            try:
                actual_config = json.dumps(
                    EditConfigIn.model_validate(json.loads(existing.config_json or "{}")).model_dump(),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            except ValueError:
                actual_config = None
            if (
                existing.task_id != task_id
                or existing.base_version != inp.baseVersion
                or actual_config != expected_config
            ):
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    detail={
                        "code": "IDEMPOTENCY_KEY_REUSED",
                        "message": "该幂等键已用于不同的重合成请求",
                    },
                )
            return render_to_out(existing)
        if task.status != "done":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "TASK_NOT_READY", "message": "仅已完成任务可重新合成"},
            )
        active = await ensure_active_render_version(db, task)
        if inp.baseVersion != active.version:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "RENDER_VERSION_CONFLICT",
                    "message": f"成片已更新到 v{active.version}，请刷新后再提交",
                },
            )
        render_history = await repo.list_renders(db, task_id, user_id)
        inflight = next(
            (item for item in render_history if item.status in {"pending", "running", "rendered"}),
            None,
        )
        if inflight is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "RENDER_IN_PROGRESS", "message": "已有重合成任务正在处理"},
            )

        from app.modules.billing.service import attach_reservation, reserve_quote

        reservation_batch = await reserve_quote(
            db,
            user_id,
            inp.quoteId,
            operation={"module": "hd_export", "measures": {"assets": 1}},
            commit=False,
        )
        reservation_id = reservation_batch.items[0].id
        render = PipelineRenderVersion(
            task_id=task.id,
            user_id=user_id,
            version=max((item.version for item in render_history), default=active.version) + 1,
            base_version=active.version,
            status="pending",
            config_json=json.dumps(inp.config.model_dump(), ensure_ascii=False),
            reservation_id=reservation_id,
            idempotency_key=inp.idempotencyKey,
        )
        try:
            db.add(render)
            await db.flush()
            await attach_reservation(db, reservation_id, user_id, render.id)
            await db.commit()
            await db.refresh(render)
        except BaseException:
            await db.rollback()
            raise

        render_id = render.id
        try:
            message_id = schedule_render(render_id)
        except Exception:
            logger.exception(
                "pipeline_render_enqueue_failed",
                task_id=task_id,
                render_id=render_id,
                user_id=user_id,
            )
            from app.modules.pipeline.render import _fail_render

            await _fail_render(db, render, "重合成队列暂不可用")
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "RENDER_QUEUE_UNAVAILABLE", "message": "重合成队列暂不可用，积分已退回"},
            ) from None
        try:
            await repo.record_render_queue_message(db, render.id, message_id)
            await db.refresh(render)
        except Exception:
            await db.rollback()
            logger.exception(
                "pipeline_render_queue_receipt_failed",
                task_id=task_id,
                render_id=render_id,
                user_id=user_id,
            )
            render = await repo.get_render(db, render_id, user_id) or render
        logger.info(
            "pipeline_render_created",
            task_id=task_id,
            render_id=render.id,
            version=render.version,
            user_id=user_id,
        )
        return render_to_out(render)


async def list_render_versions(
    db: AsyncSession,
    task_id: str,
    user_id: str,
) -> list[RenderVersionOut]:
    task = await _must_get(db, task_id, user_id)
    if task.status == "done":
        task = await repo.get_for_update(db, task_id, user_id) or task
        await ensure_active_render_version(db, task)
        await db.commit()
    return [render_to_out(item) for item in await repo.list_renders(db, task_id, user_id)]


async def get_publication_draft(
    db: AsyncSession,
    task_id: str,
    user_id: str,
) -> PublicationRevisionOut:
    task = await _must_get(db, task_id, user_id)
    if task.status != "done":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "TASK_NOT_READY", "message": "任务尚未完成，不能创建发布草稿"},
        )
    draft = await repo.latest_draft_publication_revision(db, task_id, user_id)
    if draft is None:
        latest = await repo.latest_publication_revision(db, task_id, user_id)
        revision = (latest.revision + 1) if latest else 1
        content = (
            _content_from_revision(latest)
            if latest and latest.status == "finalized"
            else _default_publication_content(task)
        )
        draft = PublicationRevision(
            user_id=user_id,
            task_id=task_id,
            revision=revision,
            status="draft",
            base_render_version_id=_base_render_version_id(task),
            content_spec_json=content.model_dump_json(),
            draft_revision=1,
        )
        db.add(draft)
        await db.commit()
        await db.refresh(draft)
    return publication_revision_to_out(draft)


async def put_publication_draft(
    db: AsyncSession,
    task_id: str,
    user_id: str,
    inp: PublicationDraftPutIn,
) -> PublicationRevisionOut:
    await _must_get(db, task_id, user_id)
    draft = await repo.latest_draft_publication_revision(db, task_id, user_id)
    if draft is None:
        latest = await repo.latest_publication_revision(db, task_id, user_id)
        if latest is not None and latest.status == "finalized":
            draft = PublicationRevision(
                user_id=user_id,
                task_id=task_id,
                revision=latest.revision + 1,
                status="draft",
                base_render_version_id=latest.render_version_id,
                content_spec_json=latest.content_spec_json,
                draft_revision=inp.draftRevision,
            )
            db.add(draft)
            await db.flush()
        else:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "PUBLICATION_DRAFT_MISSING", "message": "草稿不存在，请刷新后重试"},
            )
    result = await db.execute(
        update(PublicationRevision)
        .where(
            PublicationRevision.id == draft.id,
            PublicationRevision.user_id == user_id,
            PublicationRevision.status == "draft",
            PublicationRevision.draft_revision == inp.draftRevision,
        )
        .values(
            content_spec_json=inp.content.model_dump_json(),
            draft_revision=PublicationRevision.draft_revision + 1,
            last_error="",
            updated_at=datetime.now(UTC),
        )
        .execution_options(synchronize_session=False)
    )
    if int(getattr(result, "rowcount", 0) or 0) != 1:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "PUBLICATION_DRAFT_CONFLICT", "message": "草稿已被更新，请刷新后再保存"},
    )
    await db.commit()
    await db.refresh(draft)
    return publication_revision_to_out(draft)


_SUGGESTION_NOISE_RE = re.compile(
    r"^(第\s*[\d一二三四五六七八九十]+\s*组\s*[:：.、]?|标题\s*[:：]|标签\s*[:：]|封面\s*[:：]|[\d]+\s*[.、)]\s*)+"
)


def _clean_suggestion_text(value: object, limit: int = 60) -> str:
    """清洗 LLM 建议文本：去“第N组/标题：/序号”前缀与包裹引号，避免原文直接渗入输入框"""
    text = str(value or "").strip().strip('"“”')
    text = _SUGGESTION_NOISE_RE.sub("", text).strip()
    return text[:limit]


def _normalize_suggestion_groups(raw_groups: list) -> list[MetadataSuggestionGroupOut]:
    groups: list[MetadataSuggestionGroupOut] = []
    for raw in raw_groups:
        if not isinstance(raw, dict):
            continue
        title = _clean_suggestion_text(raw.get("title"), 40)
        if not title:
            continue
        tags_raw = raw.get("tags")
        tags = [
            _clean_suggestion_text(item, 20).lstrip("#")
            for item in (tags_raw if isinstance(tags_raw, list) else [])
        ]
        tags = [item for item in tags if item][:6]
        cover_text = _clean_suggestion_text(raw.get("coverText"), 20)
        groups.append(MetadataSuggestionGroupOut(title=title, tags=tags, coverText=cover_text))
    return groups[:3]


async def metadata_suggestions(
    db: AsyncSession,
    task_id: str,
    user_id: str,
) -> MetadataSuggestionsOut:
    task = await _must_get(db, task_id, user_id)
    content = _default_publication_content(task)
    title = content.title.strip() or task.title or "口播视频"
    script = task.script_text or str(json.loads(task.artifacts_json or "{}").get("script") or "")
    groups: list[MetadataSuggestionGroupOut] = []
    try:
        from app.providers.registry import registry

        raw_groups, _ = await registry.run_with_fallback(
            "llm",
            registry.llm_chain,
            "generate_metadata_groups",
            script or title,
            "douyin",
            3,
            trace_id=task.trace_id,
            task_id=task.id,
        )
        groups = _normalize_suggestion_groups(raw_groups if isinstance(raw_groups, list) else [])
    except Exception:  # noqa: BLE001
        logger.warning("publication_metadata_suggestion_fallback", task_id=task_id, user_id=user_id)
    if not groups:
        # 降级兑底：用任务标题/话题拼出 3 组可用建议，保证前端交互不中断
        base_tags = content.topics or [item for item in [task.topic.strip()] if item] or ["口播", "知识分享"]
        fillers = ["短视频", "个人IP", "内容运营"]
        fallback_titles = [
            title,
            title[:20] + "完整版" if len(title) > 8 else f"{title}指南",
            f"{title[:18]}实战",
        ]
        groups = [
            MetadataSuggestionGroupOut(
                title=item[:40],
                tags=(base_tags + [fillers[index % 3]])[:6],
                coverText=item[:12],
            )
            for index, item in enumerate(fallback_titles)
        ]
    return MetadataSuggestionsOut(
        titles=[group.title for group in groups][:3],
        tags=(groups[0].tags if groups else [])[:8],
        groups=groups,
    )


async def cover_candidates(
    db: AsyncSession,
    task_id: str,
    user_id: str,
) -> list[CoverCandidateOut]:
    task = await _must_get(db, task_id, user_id)
    artifacts = json.loads(task.artifacts_json or "{}")
    duration_ms = max(1, int(float(artifacts.get("duration") or 3.0) * 1000))
    defaults = [300, 1500, 2700]
    timestamps = [min(item, max(0, duration_ms - 1)) for item in defaults]
    if duration_ms < 2700:
        step = max(1, duration_ms // 4)
        timestamps = [min(duration_ms - 1, step * idx) for idx in (1, 2, 3)]
    clean_key = _clean_master_key(artifacts)
    if not clean_key:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "CLEAN_MASTER_REQUIRED", "message": "无可用于提取封面的 clean 视频源"},
        )
    if not await storage_exists(clean_key):
        # 源文件已丢失（如本地存储被清理），明确告知而非误导“稍后重试”
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "CLEAN_MASTER_MISSING",
                "message": "成片源文件已不存在（可能被清理），请重新生成成片后再选封面",
            },
        )
    cache = artifacts.get("cover_candidates")
    if not isinstance(cache, dict):
        cache = {}
    changed = False
    candidates: list[CoverCandidateOut] = []
    for timestamp in timestamps:
        key = str(cache.get(str(timestamp)) or "")
        if not key or not await storage_exists(key):
            key = await _extract_cover_candidate_frame(clean_key, timestamp)
            cache[str(timestamp)] = key
            changed = True
        candidates.append(CoverCandidateOut(timestampMs=timestamp, imageUrl=signed_media_path(key) if key else ""))
    if changed:
        artifacts["cover_candidates"] = cache
        task.artifacts_json = json.dumps(artifacts, ensure_ascii=False)
        await db.commit()
    return candidates


async def cover_preview(
    db: AsyncSession,
    task_id: str,
    user_id: str,
    inp: CoverPreviewIn,
) -> CoverPreviewOut:
    """所见即所得封面预览：按选中帧+模板+文案渲染与成片同规格的封面图。"""
    task = await _must_get(db, task_id, user_id)
    artifacts = json.loads(task.artifacts_json or "{}")
    clean_key = _clean_master_key(artifacts)
    if not clean_key:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "CLEAN_MASTER_REQUIRED", "message": "无可用于提取封面的 clean 视频源"},
        )
    if not await storage_exists(clean_key):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "CLEAN_MASTER_MISSING",
                "message": "成片源文件已不存在（可能被清理），请重新生成成片后再预览封面",
            },
        )
    from app.providers.real import _target_size, render_cover_preview_bytes

    width, height = _target_size(str(artifacts.get("ratio") or "9:16"))
    try:
        image_bytes = await render_cover_preview_bytes(
            clean_key, inp.selectedFrameMs, inp.text, inp.template, width, height
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("cover_preview_render_failed", task_id=task_id, timestamp_ms=inp.selectedFrameMs)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "COVER_PREVIEW_FAILED", "message": "封面预览生成失败，请稍后重试"},
        ) from exc
    from app.core.storage import save_bytes

    key = await save_bytes("cover-preview", f"{inp.selectedFrameMs}.jpg", image_bytes)
    return CoverPreviewOut(imageUrl=signed_media_path(key))


async def finalize_publication(
    db: AsyncSession,
    task_id: str,
    user_id: str,
    inp: PublicationFinalizeIn,
) -> PublicationRevisionOut:
    lock = _render_creation_locks.setdefault(f"publication:{task_id}", asyncio.Lock())
    async with lock:
        task = await repo.get_for_update(db, task_id, user_id)
        if task is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "任务不存在"})
        if task.status != "done":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "TASK_NOT_READY", "message": "任务尚未完成，不能定稿"},
            )
        latest = await repo.latest_publication_revision(db, task_id, user_id)
        if (
            latest is not None
            and latest.draft_revision == inp.draftRevision
            and latest.status in {"rendering", "finalized"}
            and latest.render_version_id
        ):
            return publication_revision_to_out(latest)
        draft = latest if latest is not None and latest.status == "draft" else None
        if draft is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "PUBLICATION_DRAFT_MISSING", "message": "草稿不存在，请刷新后重试"},
            )
        if draft.draft_revision != inp.draftRevision:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "PUBLICATION_DRAFT_CONFLICT", "message": "草稿已被更新，请刷新后再定稿"},
            )
        if draft.status in {"rendering", "finalized"} and draft.render_version_id:
            return publication_revision_to_out(draft)
        artifacts = json.loads(task.artifacts_json or "{}")
        clean_video_key = _clean_master_key(artifacts)
        if not clean_video_key:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "CLEAN_MASTER_REQUIRED", "message": "旧成片已烧字幕且缺少无字幕母版，不能再次烧录字幕"},
            )
        existing = await repo.get_render_by_idempotency(db, user_id, inp.idempotencyKey)
        if existing is not None:
            if existing.task_id != task_id:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    detail={"code": "IDEMPOTENCY_KEY_REUSED", "message": "该幂等键已用于其它任务"},
                )
            linked = await _revision_for_render(db, existing.id, user_id)
            if linked is not None:
                return publication_revision_to_out(linked)
        active = await ensure_active_render_version(db, task)
        if draft.base_render_version_id and draft.base_render_version_id != active.id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "RENDER_VERSION_CONFLICT", "message": "成片已更新，请刷新草稿后再定稿"},
            )
        render_history = await repo.list_renders(db, task_id, user_id)
        inflight = next((item for item in render_history if item.status in {"pending", "running", "rendered"}), None)
        if inflight is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "RENDER_IN_PROGRESS", "message": "已有渲染任务正在处理"},
            )
        from app.modules.billing.service import attach_reservation, reserve_quote

        reservation_batch = await reserve_quote(
            db,
            user_id,
            inp.quoteId,
            operation={"module": "hd_export", "measures": {"assets": 1}},
            commit=False,
        )
        reservation_id = reservation_batch.items[0].id
        content = _content_from_revision(draft)
        render = PipelineRenderVersion(
            task_id=task.id,
            user_id=user_id,
            version=max((item.version for item in render_history), default=active.version) + 1,
            base_version=active.version,
            status="pending",
            config_json=json.dumps(
                _publication_render_config(draft.id, content, clean_video_key),
                ensure_ascii=False,
            ),
            reservation_id=reservation_id,
            idempotency_key=inp.idempotencyKey,
        )
        try:
            db.add(render)
            await db.flush()
            draft.status = "rendering"
            draft.base_render_version_id = active.id
            draft.render_version_id = render.id
            draft.last_error = ""
            await attach_reservation(db, reservation_id, user_id, render.id)
            await db.commit()
            await db.refresh(draft)
            await db.refresh(render)
        except BaseException:
            await db.rollback()
            raise
        try:
            message_id = schedule_render(render.id)
        except Exception:
            logger.exception(
                "publication_render_enqueue_failed",
                task_id=task_id,
                render_id=render.id,
                revision_id=draft.id,
                user_id=user_id,
            )
            from app.modules.pipeline.render import _fail_render

            await _fail_render(db, render, "定稿渲染队列暂不可用")
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "RENDER_QUEUE_UNAVAILABLE", "message": "定稿渲染队列暂不可用，积分已退回"},
            ) from None
        await repo.record_render_queue_message(db, render.id, message_id)
        await db.refresh(draft)
        return publication_revision_to_out(draft)


async def list_publication_revisions(
    db: AsyncSession,
    task_id: str,
    user_id: str,
) -> list[PublicationRevisionOut]:
    await _must_get(db, task_id, user_id)
    return [publication_revision_to_out(item) for item in await repo.list_publication_revisions(db, task_id, user_id)]


async def _extract_cover_candidate_frame(clean_video_key: str, timestamp_ms: int) -> str:
    from app.providers.real import extract_cover_candidate_frame

    try:
        return await extract_cover_candidate_frame(clean_video_key, timestamp_ms)
    except Exception as exc:  # noqa: BLE001
        logger.exception("cover_candidate_extract_failed", video_key=clean_video_key, timestamp_ms=timestamp_ms)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "COVER_CANDIDATE_FAILED", "message": "封面候选帧提取失败，请稍后重试"},
        ) from exc


async def cancel_render(
    db: AsyncSession,
    task_id: str,
    render_id: str,
    user_id: str,
) -> RenderVersionOut:
    await _must_get(db, task_id, user_id)
    render = await repo.get_render(db, render_id, user_id)
    if render is None or render.task_id != task_id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "RENDER_NOT_FOUND", "message": "重合成版本不存在"},
        )
    if render.status in {"done", "failed", "canceled"}:
        return render_to_out(render)
    if render.status == "running":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "RENDER_ALREADY_RUNNING", "message": "成片已开始合成，当前不能取消"},
        )
    if render.status == "rendered":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "RENDER_SETTLING", "message": "成片已生成，正在结算并切换版本"},
        )
    canceled = await repo.cancel_pending_render(db, render.id, user_id, task_id)
    if not canceled:
        current = await repo.get_render(db, render_id, user_id)
        if current is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail={"code": "RENDER_NOT_FOUND", "message": "重合成版本不存在"},
            )
        if current.status in {"done", "failed", "canceled"}:
            return render_to_out(current)
        if current.status == "running":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "RENDER_ALREADY_RUNNING", "message": "成片已开始合成，当前不能取消"},
            )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "RENDER_SETTLING", "message": "成片已生成，正在结算并切换版本"},
        )
    await db.refresh(render)
    if render.reservation_id:
        from app.modules.billing.service import release_reservation

        released = await release_reservation(db, render.reservation_id, user_id)
        if released is None or released.status != "released":
            await db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "RENDER_SETTLING", "message": "积分状态已变化，无法取消该成片"},
            )
    else:
        await db.commit()
    await db.refresh(render)
    logger.info(
        "pipeline_render_canceled",
        task_id=task_id,
        render_id=render_id,
        user_id=user_id,
    )
    return render_to_out(render)


async def ensure_active_render_version(
    db: AsyncSession,
    task: PipelineTask,
) -> PipelineRenderVersion:
    """为迁移前的完成任务补建 v1；已有版本只修正活动指针。"""
    renders = await repo.list_renders(db, task.id, task.user_id)
    active = next((item for item in renders if item.is_active), None)
    if active is not None:
        task.active_render_version = active.version
        return active
    completed = next((item for item in renders if item.status == "done"), None)
    if completed is not None:
        completed.is_active = True
        task.active_render_version = completed.version
        return completed

    artifacts = json.loads(task.artifacts_json or "{}")
    video_key = str(artifacts.get("final_video_key") or "")
    cover_key = str(artifacts.get("cover_key") or "")
    quality = artifacts.get("quality")
    if not video_key or not isinstance(quality, dict) or not quality.get("passed"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "VIDEO_NOT_READY", "message": "成片缺失或未通过质量检查"},
        )
    config = _edit_config_from_artifacts(artifacts)
    initial = PipelineRenderVersion(
        task_id=task.id,
        user_id=task.user_id,
        version=1,
        base_version=0,
        status="done",
        config_json=json.dumps(config.model_dump(), ensure_ascii=False),
        reservation_id=task.reservation_id,
        idempotency_key=f"bootstrap:{task.id}",
        video_key=video_key,
        cover_key=cover_key,
        quality_json=json.dumps(quality, ensure_ascii=False),
        is_active=True,
    )
    db.add(initial)
    task.active_render_version = 1
    artifacts["render_version"] = 1
    artifacts["edit_config"] = config.model_dump()
    await db.flush()
    artifacts["render_version_id"] = initial.id
    task.artifacts_json = json.dumps(artifacts, ensure_ascii=False)
    return initial


def _edit_config_from_artifacts(artifacts: dict) -> EditConfigIn:
    raw = artifacts.get("edit_config")
    if isinstance(raw, dict):
        try:
            return EditConfigIn.model_validate(raw)
        except ValueError:
            pass
    return EditConfigIn()


async def create_retry_quote(db: AsyncSession, task_id: str, user_id: str) -> dict:
    """基于服务端保存的原任务参数重建报价，避免前端漏报计费模块。"""
    from app.modules.billing.service import get_quota, pipeline_quote_quantities, save_quote
    from app.modules.catalog import repository as catalog_repo
    from app.modules.catalog.service import build_quote

    task = await _must_get(db, task_id, user_id)
    version = await catalog_repo.active_price_version(db)
    if version is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "NO_PRICE_VERSION", "message": "未发布价格版本"},
        )
    prices = await catalog_repo.module_prices(db, version.id)
    quantities = pipeline_quote_quantities(
        await _task_for_quote(db, task),
        {price.module: price.billing_unit for price in prices},
    )
    if not quantities:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "PRICE_NOT_FOUND", "message": "流水线价格配置不完整，暂时无法重试"},
        )
    quote = await build_quote(
        db,
        [{"module": module, "quantity": quantity} for module, quantity in quantities.items()],
    )
    catalog_version_id = str(quote.pop("_catalogVersionId"))
    await save_quote(db, user_id, quote, catalog_version_id)
    quote["availablePoints"] = (await get_quota(db, user_id)).balance
    return quote


async def retry_step(
    db: AsyncSession,
    task_id: str,
    step: str,
    user_id: str,
    quote_id: str | None = None,
) -> TaskOut:
    """单步重跑：重置该步及后续步骤，从断点续跑（F-405）"""
    _check_step(step)
    t = await _must_get(db, task_id, user_id)
    if t.status == "reconciliation_required":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "RECONCILIATION_REQUIRED", "message": "外部服务结果未知，管理员对账前不可重试"},
        )
    if t.status == "running":
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail={"code": "TASK_RUNNING", "message": "任务运行中，稍后再试"}
        )
    if t.status in {"done", "canceled"}:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "TASK_TERMINAL", "message": "已结束任务不可重试"},
        )
    needs_reservation = False
    if t.reservation_id:
        from app.modules.billing.models import CreditReservation

        reservation = await db.get(CreditReservation, t.reservation_id)
        if reservation is None or reservation.status != "reserved":
            needs_reservation = True
    elif settings.app_env != "dev":
        needs_reservation = True
    if needs_reservation:
        if not quote_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "RETRY_REQUIRES_NEW_QUOTE",
                    "message": "原积分冻结已结束，请重新报价后重试",
                },
            )
        from app.modules.billing.service import attach_reservation, reserve_quote

        batch = await reserve_quote(
            db,
            user_id,
            quote_id,
            task=await _task_for_quote(db, t),
            commit=False,
        )
        t.reservation_id = batch.items[0].id
        await attach_reservation(db, t.reservation_id, user_id, t.id)
    _clear_artifacts_from(t, step)
    t.status = "pending"
    t.error = ""
    t.queue_message_id = ""
    await repo.save(db, t)
    try:
        message_id = schedule_run(t.id, from_step=step)
    except Exception:
        logger.exception("pipeline_retry_enqueue_failed", task_id=task_id, step=step, user_id=user_id)
        t.status = "failed"
        t.error = "任务队列暂不可用，积分已恢复，请重新报价后重试"
        await repo.save(db, t)
        if t.reservation_id:
            from app.modules.billing.service import release_reservation

            await release_reservation(db, t.reservation_id, user_id)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "PIPELINE_QUEUE_UNAVAILABLE", "message": "任务队列暂不可用，积分已恢复"},
        ) from None
    try:
        await repo.record_queue_message(db, t.id, message_id)
    except Exception:
        await db.rollback()
        logger.exception(
            "pipeline_retry_queue_receipt_failed",
            task_id=task_id,
            step=step,
            user_id=user_id,
            message_id=message_id,
        )
    await db.refresh(t)
    # 单步重跑：记录 INFO（§10.6.8-B #1）
    logger.info("task_retry", task_id=task_id, step=step, user_id=user_id)
    return to_out(t)


async def confirm(db: AsyncSession, task_id: str, user_id: str) -> TaskOut:
    """manual 模式逐步确认（waiting_confirm → 续跑下一步）"""
    t = await _must_get(db, task_id, user_id)
    if t.status != "waiting_confirm":
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "NOT_WAITING", "message": "任务不在待确认状态"})
    t.status = "pending"
    t.queue_message_id = ""
    await repo.save(db, t)
    try:
        message_id = schedule_run(t.id)
    except Exception:
        logger.exception("pipeline_confirm_enqueue_failed", task_id=task_id, user_id=user_id)
        t.status = "waiting_confirm"
        t.queue_message_id = ""
        await repo.save(db, t)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "PIPELINE_QUEUE_UNAVAILABLE", "message": "任务队列暂不可用，请稍后再次确认"},
        ) from None
    try:
        await repo.record_queue_message(db, t.id, message_id)
    except Exception:
        await db.rollback()
        logger.exception(
            "pipeline_confirm_queue_receipt_failed",
            task_id=task_id,
            user_id=user_id,
            message_id=message_id,
        )
    await db.refresh(t)
    # manual 确认：记录 INFO（§10.6.8-B #1）
    logger.info("task_confirmed", task_id=task_id, user_id=user_id)
    return to_out(t)


async def cancel(db: AsyncSession, task_id: str, user_id: str) -> TaskOut:
    t = await _must_get(db, task_id, user_id)
    if t.status == "reconciliation_required":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "RECONCILIATION_REQUIRED", "message": "外部服务结果未知，管理员对账前不可取消"},
        )
    if t.status in ("done", "failed", "canceled"):
        return to_out(t)
    t.status = "canceled"
    await repo.save(db, t)
    if t.reservation_id:
        from app.modules.billing.service import release_reservation

        await release_reservation(db, t.reservation_id, user_id)
    # 任务取消：记录 INFO（§10.6.8-B #1）
    logger.info("task_canceled", task_id=task_id, user_id=user_id)
    return to_out(t)


async def stats(db: AsyncSession, user_id: str) -> StatsOut:
    return StatsOut(**await repo.stats(db, user_id))


async def recover_incomplete_tasks(db: AsyncSession) -> int:
    """API 重启时补投安全步骤；结果未知的非幂等步骤禁止自动重放。"""
    # Pipeline actor 最长执行 30 分钟；API 滚动重启不能抢走仍在工作的任务。
    tasks = await repo.list_recoverable(
        db,
        running_stale_before=datetime.now(UTC) - timedelta(minutes=35),
    )
    recoverable: list[tuple[PipelineTask, str | None]] = []
    for task in tasks:
        from_step = task.current_step or None if task.status == "running" else None
        artifacts = json.loads(task.artifacts_json or "{}")
        provider_result_unknown = task.status == "running" and (
            from_step == "voice" or (from_step == "avatar" and not artifacts.get("avatar_render_task_id"))
        )
        if provider_result_unknown:
            step_name = "语音" if from_step == "voice" else "数字人"
            task.status = "reconciliation_required"
            task.queue_message_id = ""
            task.error = f"{from_step}: 外部服务结果未知，为避免重复调用已停止自动恢复，等待管理员对账"
            logger.error(
                "pipeline_recovery_requires_reconciliation",
                task_id=task.id,
                user_id=task.user_id,
                step=from_step,
            )
            from app.modules.notify.service import notify_user

            await notify_user(
                db,
                task.user_id,
                "error",
                f"任务需要人工确认：{task.title}",
                f"{step_name}外部服务结果未知，为避免重复调用已停止自动恢复；积分冻结保留，等待管理员对账。",
            )
            continue
        task.status = "pending"
        task.queue_message_id = ""
        recoverable.append((task, from_step))
    if tasks:
        await db.commit()
    for task, from_step in recoverable:
        message_id = schedule_run(task.id, from_step)
        await repo.record_queue_message(db, task.id, message_id)
    if recoverable:
        logger.warning("pipeline_tasks_recovered", count=len(recoverable))
    return len(recoverable)


async def recover_render_versions(db: AsyncSession) -> int:
    """重启后恢复本地可重放的重合成；已渲染版本只继续结算和切换。"""
    # Worker 最长执行 30 分钟；额外留 5 分钟，避免 API 单独重启时重投仍在运行的任务。
    renders = await repo.list_recoverable_renders(
        db,
        running_stale_before=datetime.now(UTC) - timedelta(minutes=35),
    )
    for render in renders:
        if render.status == "running":
            render.status = "pending"
        render.queue_message_id = ""
    if renders:
        await db.commit()
    for render in renders:
        message_id = schedule_render(render.id)
        await repo.record_render_queue_message(db, render.id, message_id)
    if renders:
        logger.warning("pipeline_renders_recovered", count=len(renders))
    return len(renders)


async def _task_for_quote(db: AsyncSession, task: PipelineTask) -> dict:
    from app.modules.ipasset import repository as ipasset_repo

    persona = await ipasset_repo.get(db, task.ip_id, task.user_id)
    return {
        "ipId": task.ip_id,
        "sourceUrl": task.source_url,
        "topic": task.topic,
        "scriptText": task.script_text,
        "scriptId": task.script_id or None,
        "scriptVersion": task.script_version or None,
        "voiceId": task.voice_id,
        "avatarId": task.avatar_id,
        "platforms": json.loads(task.platforms_json or "[]"),
        "_targetDurationSeconds": max(1, persona.video_duration if persona else 60),
    }


def _clear_artifacts_from(task: PipelineTask, step: str) -> None:
    """显式重试会清除该步及后续产物；重启恢复则保留供应商任务号。"""
    outputs = {
        "parse": {"video_key", "title", "platform"},
        "asr": {"transcript", "words"},
        "rewrite": {"script", "similarity", "topic_candidates"},
        "voice": {"audio_key", "tts_words", "duration"},
        "avatar": {"avatar_render_task_id", "avatar_provider", "avatar_video_key", "duration"},
        "compose": {
            "clean_video_key",
            "subtitle_enabled",
            "cover_candidates",
            "final_video_key",
            "cover_key",
            "quality",
            "duration",
        },
        "edit": {"edited"},
        "publish": {"publish_job_ids"},
    }
    artifacts = json.loads(task.artifacts_json or "{}")
    start = STEP_ORDER.index(step)
    for name in STEP_ORDER[start:]:
        for key in outputs[name]:
            artifacts.pop(key, None)
    task.artifacts_json = json.dumps(artifacts, ensure_ascii=False)


def _check_step(step: str) -> None:
    if step not in STEP_ORDER:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "BAD_STEP", "message": f"非法步骤：{step}"}
        )


async def _must_get(db: AsyncSession, task_id: str, user_id: str) -> PipelineTask:
    t = await repo.get(db, task_id, user_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "任务不存在"})
    return t


def _base_render_version_id(task: PipelineTask) -> str:
    artifacts = json.loads(task.artifacts_json or "{}")
    return str(artifacts.get("render_version_id") or "")


def _content_from_revision(revision: PublicationRevision) -> PublicationContentIn:
    try:
        return PublicationContentIn.model_validate(json.loads(revision.content_spec_json or "{}"))
    except ValueError:
        return PublicationContentIn(title="未命名发布")


def _default_publication_content(task: PipelineTask) -> PublicationContentIn:
    artifacts = json.loads(task.artifacts_json or "{}")
    title = str(artifacts.get("cover_title") or artifacts.get("title") or task.title or "").strip()
    if not title or title == "未命名任务":
        title = str(artifacts.get("script") or task.script_text or "未命名发布")[:40]
    topics = [item for item in [task.topic.strip()] if item]
    words = artifacts.get("tts_words") or artifacts.get("words") or []
    segments = _subtitle_segments_from_words(words)
    subtitles = PublicationSubtitlesIn.model_validate(
        {
            "enabled": bool(segments),
            "source": "tts_fallback",
            "segments": segments,
        }
    )
    return PublicationContentIn(
        title=title[:80],
        topics=topics[:8],
        subtitles=subtitles,
    )


def _subtitle_segments_from_words(words: list) -> list[dict]:
    segments: list[dict] = []
    current: list[dict] = []
    length = 0
    for raw in words[:240]:
        if not isinstance(raw, dict):
            continue
        try:
            text = str(raw.get("word") or "").strip()
            start = float(raw.get("start") or 0)
            end = float(raw.get("end") or 0)
        except (TypeError, ValueError):
            continue
        if not text:
            continue
        if current and start - float(current[-1]["end"]) > 0.5:
            segments.append(_subtitle_segment(len(segments) + 1, current))
            current, length = [], 0
        current.append({"word": text, "start": start, "end": end})
        length += len(text)
        tail = text[-1:]
        if tail in "。！？!?；;" or length >= 16 or (tail in "，,、：:" and length >= 10):
            segments.append(_subtitle_segment(len(segments) + 1, current))
            current, length = [], 0
    if current:
        segments.append(_subtitle_segment(len(segments) + 1, current))
    return segments


def _subtitle_segment(index: int, words: list[dict]) -> dict:
    return {
        "id": f"s{index}",
        "startMs": max(0, round(float(words[0]["start"]) * 1000)),
        "endMs": max(1, round(float(words[-1]["end"]) * 1000)),
        "text": "".join(str(word["word"]) for word in words),
    }


def _clean_master_key(artifacts: dict) -> str:
    clean_key = str(artifacts.get("clean_video_key") or "")
    if clean_key:
        return clean_key
    # 存量无字幕活动成片可视作 clean master；已烧字幕但未保存 clean master 必须阻止二次烧录。
    if artifacts.get("subtitle_enabled") is True:
        return ""
    return str(artifacts.get("final_video_key") or "")


def _publication_render_config(
    revision_id: str,
    content: PublicationContentIn,
    clean_video_key: str,
) -> dict:
    style = content.subtitles.style.model_dump()
    return {
        "publication_revision_id": revision_id,
        "content": content.model_dump(),
        "clean_video_key": clean_video_key,
        "subtitleEnabled": content.subtitles.enabled,
        "subtitleStyle": style,
        "bgmMode": "off",
        "bgmVolume": 0,
        "coverTemplate": content.cover.template,
    }


async def _revision_for_render(
    db: AsyncSession,
    render_id: str,
    user_id: str,
) -> PublicationRevision | None:
    return (
        await db.execute(
            select(PublicationRevision).where(
                PublicationRevision.render_version_id == render_id,
                PublicationRevision.user_id == user_id,
            )
        )
    ).scalar_one_or_none()


def publication_revision_to_out(revision: PublicationRevision) -> PublicationRevisionOut:
    return PublicationRevisionOut(
        id=revision.id,
        taskId=revision.task_id,
        revision=revision.revision,
        status=revision.status,
        baseRenderVersionId=revision.base_render_version_id,
        renderVersionId=revision.render_version_id,
        content=_content_from_revision(revision),
        draftRevision=revision.draft_revision,
        lastError=revision.last_error,
        finalizedAt=revision.finalized_at.astimezone(UTC).isoformat() if revision.finalized_at else None,
        createdAt=revision.created_at.astimezone(UTC).isoformat(),
        updatedAt=revision.updated_at.astimezone(UTC).isoformat(),
    )


def to_out(t: PipelineTask) -> TaskOut:
    steps_raw = json.loads(t.steps_json or "[]") or _default_steps()
    ctx = json.loads(t.artifacts_json or "{}")
    cover = str(ctx.get("cover_key") or "")
    final_video = str(ctx.get("final_video_key") or "")
    public_ctx = public_metadata(ctx, redact_values=True)
    if final_video:
        public_ctx["final_video_url"] = signed_media_path(final_video)
    if cover:
        public_ctx["cover_url"] = signed_media_path(cover)
    public_steps: list[StepStateOut] = []
    for step in steps_raw:
        public_step = {
            **step,
            "provider": "",
            "message": "处理失败，请稍后重试" if step.get("status") == "failed" else step.get("message", ""),
            "artifacts": public_metadata(step.get("artifacts", {}), redact_values=True),
        }
        public_steps.append(StepStateOut(**public_step))
    return TaskOut(
        id=t.id,
        ipId=t.ip_id,
        scriptId=getattr(t, "script_id", ""),
        scriptVersion=getattr(t, "script_version", 0),
        title=t.title,
        coverUrl=signed_media_path(cover) if cover else None,
        sourceUrl=t.source_url,
        mode=t.mode,
        status=t.status,
        steps=public_steps,
        currentStep=t.current_step or None,
        compute=t.compute,
        quotaCost=t.quota_cost,
        error="处理失败，请稍后重试" if t.error else "",
        artifacts=public_ctx,
        activeRenderVersion=getattr(t, "active_render_version", 0),
        batchId=t.batch_id,
        createdAt=t.created_at.astimezone(UTC).isoformat(),
        updatedAt=t.updated_at.astimezone(UTC).isoformat(),
    )


def render_to_out(render: PipelineRenderVersion) -> RenderVersionOut:
    config = EditConfigIn.model_validate(json.loads(render.config_json or "{}"))
    quality = json.loads(render.quality_json or "{}")
    return RenderVersionOut(
        id=render.id,
        taskId=render.task_id,
        version=render.version,
        baseVersion=render.base_version,
        status=render.status,
        config=config,
        videoUrl=signed_media_path(render.video_key) if render.video_key else None,
        coverUrl=signed_media_path(render.cover_key) if render.cover_key else None,
        quality=quality if isinstance(quality, dict) else {},
        error="重新合成失败，请稍后重试" if render.error else "",
        isActive=render.is_active,
        createdAt=render.created_at.astimezone(UTC).isoformat(),
        updatedAt=render.updated_at.astimezone(UTC).isoformat(),
    )


def schedule_render(render_id: str) -> str:
    from app.workers.tasks import run_pipeline_render

    message = run_pipeline_render.send(render_id)
    return message.message_id
