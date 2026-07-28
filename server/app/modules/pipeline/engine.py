"""
流水线引擎（06 文档 §10.2）
状态机: PENDING → RUNNING(step1..8) → DONE / FAILED
每步: emit(running) → ComputeRouter.pick(step) → step.run(ctx)
      → 失败时按降级链换 Provider 重试 → artifacts 落库 → emit(done, 计量事件)
mode=manual 时每步完成暂停等待用户确认（F-405 单步干预）
支持单步重跑 /retry；文案和剪辑修改通过版本化接口提交；批量任务扇出 + 并发闸门(≥5)
日志：step_failed/task_failed 结构化字段（§10.6.8-A #3）
"""

import base64
import json
import mimetypes
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.distributed_semaphore import DistributedSemaphore, SemaphoreUnavailableError
from app.core.events import CHANNEL_FEED, CHANNEL_TASKS, publish
from app.core.logging import get_logger, task_id_var, trace_id_var, user_id_var
from app.core.runtime_limits import PIPELINE_SEMAPHORE_LEASE_SECONDS
from app.core.white_label import public_error_message
from app.modules.notify.service import notify_user
from app.providers.base import ComposeInput, is_mock_provider
from app.providers.registry import registry

from .models import STEP_ORDER, PipelineTask
from .repository import claim_for_run
from .repository import get as repo_get
from .repository import save as repo_save

logger = get_logger("oral.pipeline.engine")
settings = get_settings()

# 并发闸门（F-406）：生产跨 Worker 共享，开发/测试回落进程内。
_gate = DistributedSemaphore(
    "pipeline",
    limit=settings.pipeline_max_concurrency,
    lease_seconds=PIPELINE_SEMAPHORE_LEASE_SECONDS,
)
_running: set[str] = set()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load_steps(task: PipelineTask) -> list[dict]:
    steps = json.loads(task.steps_json or "[]")
    if not steps:
        steps = [
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
    return steps


def _dump_steps(task: PipelineTask, steps: list[dict]) -> None:
    task.steps_json = json.dumps(steps, ensure_ascii=False)


def _load_artifacts(task: PipelineTask) -> dict:
    return json.loads(task.artifacts_json or "{}")


def _dump_artifacts(task: PipelineTask, artifacts: dict) -> None:
    task.artifacts_json = json.dumps(artifacts, ensure_ascii=False)


async def _persist_intermediate_artifacts(task_id: str, values: dict) -> None:
    """在非幂等供应商提交后立即落库，Worker 重启时只恢复轮询。"""
    async with SessionLocal() as db:
        task = await repo_get(db, task_id)
        if task is None:
            raise RuntimeError("任务不存在，无法保存供应商任务号")
        artifacts = _load_artifacts(task)
        artifacts.update(values)
        _dump_artifacts(task, artifacts)
        await repo_save(db, task)


async def _emit(task: PipelineTask) -> None:
    """任务进度推送（WS 网关 → 各端，≤2s）"""
    await publish(CHANNEL_TASKS, {"kind": "task_updated", "taskId": task.id, "userId": task.user_id})


async def _feed(user_id: str, type_: str, text: str) -> None:
    import uuid

    await publish(
        CHANNEL_FEED,
        {
            "kind": "feed",
            "event": {"id": uuid.uuid4().hex[:12], "type": type_, "text": text, "createdAt": _now()},
            "userId": user_id,
        },
    )


# ============ 各步骤执行（Step.run 统一接口） ============


async def _guard_mock_result(task: PipelineTask, step: str, provider: str, result: dict) -> dict:
    """Mock 降级结果防线（与注册表启动自检双保险）：
    - 非 dev/test：Mock 产物视为该步失败，绝不允许演示数据以真实数据面貌交付用户
    - dev/test：放行但在步骤产物写入 degraded_mock 标记，并推送任务中心提示
    """
    if not provider or not is_mock_provider(provider):
        return result
    if get_settings().app_env not in {"dev", "test"}:
        raise RuntimeError(f"{step} 步降级产生了演示数据，已拒收；请检查供应商配置后重试")
    result["degraded_mock"] = True
    await publish(
        CHANNEL_TASKS,
        {
            "kind": "degraded_mock",
            "taskId": task.id,
            "userId": task.user_id,
            "step": step,
            "message": f"{step} 步已降级为演示数据（仅开发/测试环境允许）",
        },
    )
    return result


async def step_parse(task: PipelineTask, ctx: dict) -> dict:
    if task.script_text:
        return {"skipped": True, "script": task.script_text}
    if task.source_url:
        result, provider = await registry.run_with_fallback(
            "parse", registry.parse_chain, "parse_url", task.source_url, trace_id=task.trace_id, task_id=task.id
        )
        return await _guard_mock_result(
            task,
            "parse",
            provider,
            {
                "video_key": result.video_key or "",
                "title": result.title,
                "platform": result.platform,
                "provider": provider,
            },
        )
    if task.topic:
        return {"skipped": True, "topic": task.topic}
    raise RuntimeError("缺少输入（链接/选题/文案至少一项）")


async def step_asr(task: PipelineTask, ctx: dict) -> dict:
    if ctx.get("script"):
        return {"skipped": True}
    video_key = ctx.get("video_key")
    if not video_key:
        if ctx.get("topic"):
            return {"skipped": True}
        raise RuntimeError("无可转写视频")
    tr, provider = await registry.run_with_fallback(
        "asr", registry.asr_chain, "transcribe", video_key, trace_id=task.trace_id, task_id=task.id
    )
    return await _guard_mock_result(
        task,
        "asr",
        provider,
        {
            "transcript": tr.text,
            "words": [{"word": w.word, "start": w.start, "end": w.end} for w in tr.words],
            "provider": provider,
        },
    )


async def step_rewrite(task: PipelineTask, ctx: dict) -> dict:
    # 向导第 2 步已完成文案二创并确认时，script_text 即最终口播稿，直接复用不再仿写
    if task.script_text:
        return {"skipped": True, "script": task.script_text}
    source = ctx.get("script") or ctx.get("transcript") or ctx.get("topic") or ""

    # 人设引擎注入：查询任务关联的 persona（ip_id 即 persona_id）
    persona_ctx = ""
    persona = None
    if task.ip_id:
        from app.modules.ipasset.repository import get as get_persona
        from app.modules.ipasset.service import persona_prompt_context

        async with SessionLocal() as db:
            persona = await get_persona(db, task.ip_id, task.user_id)
        if persona:
            persona_ctx = persona_prompt_context(persona)

    duration = persona.video_duration if persona else 60
    taboo_words = ""
    cta_style = "关注收藏"
    avoid_topics: list[str] = []
    if persona:
        import json as _json_mod

        taboo_words = "、".join(_json_mod.loads(persona.taboo_words or "[]"))
        cta_style = persona.cta_style or "关注收藏"
        avoid_topics = _json_mod.loads(persona.avoid_topics or "[]")

    # 选题模式：先生成文案
    if not ctx.get("transcript") and ctx.get("topic") and not task.script_text:
        topics, provider = await registry.run_with_fallback(
            "llm", registry.llm_chain, "generate_topics", ctx["topic"], 5, trace_id=task.trace_id, task_id=task.id
        )
        ctx["topic_candidates"] = topics

    text_source = source or task.script_text
    intensity = getattr(task, "intensity", "structure") or "structure"

    # 三阶段仿写引擎（走降级链，确保主 Provider 故障时自动切换）
    if intensity == "light":
        # light 模式：跳过结构拆解和大纲，直接人设润色
        text, provider = await registry.run_with_fallback(
            "llm", registry.llm_chain, "polish_light", text_source, persona_ctx, trace_id=task.trace_id, task_id=task.id
        )
        sim, _ = await registry.run_with_fallback(
            "llm",
            registry.llm_chain,
            "check_similarity",
            text,
            text_source or None,
            trace_id=task.trace_id,
            task_id=task.id,
        )
        return {
            "script": text,
            "similarity": sim.score,
            "provider": provider,
            "_validation_passed": sim.score <= 60,
        }

    if not text_source and ctx.get("topic"):
        # 选题模式：无原文，使用 theme 模式从主题创作
        structure, provider = await registry.run_with_fallback(
            "llm",
            registry.llm_chain,
            "analyze_structure",
            ctx["topic"],
            "theme",
            trace_id=task.trace_id,
            task_id=task.id,
        )
        outline, _ = await registry.run_with_fallback(
            "llm",
            registry.llm_chain,
            "generate_outline",
            structure,
            persona_ctx,
            "theme",
            duration,
            trace_id=task.trace_id,
            task_id=task.id,
        )
    elif intensity == "theme":
        # theme 模式：仅提取主题关键词，全新创作
        structure, provider = await registry.run_with_fallback(
            "llm",
            registry.llm_chain,
            "analyze_structure",
            text_source,
            "theme",
            trace_id=task.trace_id,
            task_id=task.id,
        )
        outline, _ = await registry.run_with_fallback(
            "llm",
            registry.llm_chain,
            "generate_outline",
            structure,
            persona_ctx,
            "theme",
            duration,
            trace_id=task.trace_id,
            task_id=task.id,
        )
    else:
        # structure 模式：完整拆解 + IP化大纲
        structure, provider = await registry.run_with_fallback(
            "llm", registry.llm_chain, "analyze_structure", text_source, "full", trace_id=task.trace_id, task_id=task.id
        )
        outline, _ = await registry.run_with_fallback(
            "llm",
            registry.llm_chain,
            "generate_outline",
            structure,
            persona_ctx,
            "structure",
            duration,
            trace_id=task.trace_id,
            task_id=task.id,
        )

    constraints = {"duration": duration, "cta_style": cta_style, "taboo_words": taboo_words or "无"}
    text, _ = await registry.run_with_fallback(
        "llm",
        registry.llm_chain,
        "generate_script",
        outline,
        persona_ctx,
        constraints,
        trace_id=task.trace_id,
        task_id=task.id,
    )

    # 校验闭环（最多2轮）
    validation_passed = True
    for _round in range(2):
        issues = []
        if persona:
            import json as _j

            found_taboo = [w for w in _j.loads(persona.taboo_words or "[]") if w in text]
            if found_taboo:
                issues.append(f"包含禁忌词：{'、'.join(found_taboo)}")
            found_avoid = [t for t in avoid_topics if t in text]
            if found_avoid:
                issues.append(f"涉及回避话题：{'、'.join(found_avoid)}")
        sim, _ = await registry.run_with_fallback(
            "llm",
            registry.llm_chain,
            "check_similarity",
            text,
            text_source or None,
            trace_id=task.trace_id,
            task_id=task.id,
        )
        if sim.score > 60:
            issues.append(f"相似度偏高（{sim.score:.0f}分）")
        if not issues:
            break
        validation_passed = False
        text, _ = await registry.run_with_fallback(
            "llm",
            registry.llm_chain,
            "validation_rewrite",
            text,
            persona_ctx,
            "\n".join(issues),
            trace_id=task.trace_id,
            task_id=task.id,
        )
    else:
        # 循环耗尽（文本被重写过），重新检测最终相似度
        sim, _ = await registry.run_with_fallback(
            "llm",
            registry.llm_chain,
            "check_similarity",
            text,
            text_source or None,
            trace_id=task.trace_id,
            task_id=task.id,
        )
        validation_passed = sim.score <= 60

    return {"script": text, "similarity": sim.score, "provider": provider, "_validation_passed": validation_passed}


async def step_voice(task: PipelineTask, ctx: dict) -> dict:
    script = ctx.get("script") or task.script_text
    voice_id = task.voice_id
    if not voice_id:
        raise RuntimeError("未指定声音，请先克隆声音")
    # 解析用户 voice_id → provider_voice_id
    from app.modules.voice.repository import get as get_voice

    async with SessionLocal() as db:
        v = await get_voice(db, voice_id, task.user_id)
        if v is None:
            raise RuntimeError("声音不存在或不属于当前用户")
        if v.status != "ready":
            raise RuntimeError("声音尚未就绪，请先完成克隆确认")
        if not v.provider_voice_id:
            raise RuntimeError("声音供应商资产缺失，请重新克隆")
        voice_id = v.provider_voice_id
    result, provider = await registry.run_with_fallback(
        "voice", registry.voice_chain, "synthesize", voice_id, script, 1.0, trace_id=task.trace_id, task_id=task.id
    )
    # 字幕精准同步：TTS 平摊时间戳不可信，对成品音频做 ASR 对齐拿真实字级时间戳
    tts_words = await _align_tts_words(task, result.audio_key, script or "", result.duration)
    if not tts_words:
        tts_words = [{"word": w.word, "start": w.start, "end": w.end} for w in result.words]
    return await _guard_mock_result(
        task,
        "voice",
        provider,
        {
            "audio_key": result.audio_key,
            "tts_words": tts_words,
            "duration": result.duration,
            "provider": provider,
        },
    )


# ASR 请求体内嵌 data URI 上限（与 content 模块 _MAX_ASR_DATA_URI_BYTES 保持一致）
_MAX_ASR_DATA_URI_BYTES = 20 * 1024 * 1024


async def _asr_media_input(audio_key: str, duration: float) -> str:
    """ASR 取址三级策略（对齐 content 模块实践）：
    ① 公网 URL 可达 → 直接回源（省 base64，长音频异步模式也能用）
    ② 短音频（≤Flash 阈值）→ base64 data URI 内嵌，零配置直通
    ③ 都不满足 → 返回空串，调用方回退平摊时间戳
    """
    from app.core.dynamic_config import get_config_int
    from app.core.storage import get_accessible_url, read_bytes
    from app.modules.content.service import _is_public_media_url

    audio_url = await get_accessible_url(audio_key)
    if _is_public_media_url(audio_url):
        return audio_url
    # 长音频只能走异步转写（要求公网回源），data URI 帮不上
    threshold = await get_config_int("asr_flash_threshold_sec", 300)
    if duration <= 0 or duration > threshold:
        return ""
    data = await read_bytes(audio_key)
    media_type = mimetypes.guess_type(audio_key)[0] or "audio/mpeg"
    data_uri = f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"
    return data_uri if len(data_uri) <= _MAX_ASR_DATA_URI_BYTES else ""


async def _align_tts_words(task: PipelineTask, audio_key: str, script: str, duration: float) -> list[dict]:
    """对 TTS 音频跑 ASR 取真实语音时间戳，对齐回脚本字符；任何失败回退平摊时间戳（不阻断流水线）"""
    if not script.strip() or not audio_key:
        return []
    try:
        from app.providers.align import align_script_to_asr

        media_input = await _asr_media_input(audio_key, duration)
        if not media_input:
            logger.warning("subtitle_align_no_media_input", extra={"task_id": task.id})
            return []
        tr, _ = await registry.run_with_fallback(
            "asr",
            registry.asr_chain,
            "transcribe",
            media_input,
            duration or None,
            trace_id=task.trace_id,
            task_id=task.id,
        )
        aligned = align_script_to_asr(script, tr.words)
        if not aligned:
            logger.warning("subtitle_align_low_match", extra={"task_id": task.id})
            return []
        return [{"word": w.word, "start": w.start, "end": w.end} for w in aligned]
    except Exception:
        logger.warning("subtitle_align_failed", exc_info=True, extra={"task_id": task.id})
        return []


async def step_avatar(task: PipelineTask, ctx: dict) -> dict:
    from app.modules.avatar.service import resolve_provider_avatar_id

    async with SessionLocal() as db:
        avatar_id = await resolve_provider_avatar_id(db, task.user_id, task.avatar_id)

    # 音频驱动视频生成：上传音频 → 创建任务 → 轮询 → 下载转存
    audio_key = ctx.get("audio_key", "")
    render_task_id = str(ctx.get("avatar_render_task_id") or "")
    provider = str(ctx.get("avatar_provider") or "")
    if not render_task_id:
        render_task_id, provider = await registry.run_with_fallback(
            "avatar",
            registry.avatar_chain,
            "create_by_audio",
            avatar_id,
            audio_key,
            trace_id=task.trace_id,
            task_id=task.id,
        )
        durable = {"avatar_render_task_id": render_task_id, "avatar_provider": provider}
        await _persist_intermediate_artifacts(task.id, durable)
        ctx.update(durable)

    # 轮询视频生成任务直到完成
    result, _ = await registry.run_with_fallback(
        "avatar", registry.avatar_chain, "poll_video_task", render_task_id, trace_id=task.trace_id, task_id=task.id
    )

    # 下载临时视频 URL 转存到自有存储（白标）
    video_url = result.get("video_url", "")
    duration = result.get("duration", 0)
    video_key = ""
    if video_url:
        video_key, _ = await registry.run_with_fallback(
            "avatar", registry.avatar_chain, "download_video", video_url, trace_id=task.trace_id, task_id=task.id
        )

    return await _guard_mock_result(
        task, "avatar", provider, {"avatar_video_key": video_key, "duration": duration, "provider": provider}
    )


async def step_compose(task: PipelineTask, ctx: dict) -> dict:
    return await _compose_with_ctx(task, ctx)


def _subtitle_style_from_ctx(ctx: dict) -> dict:
    """剪辑台保存的字幕配置（override 写入 ctx，JSON 字符串容错），无配置用默认样式"""
    raw = ctx.get("subtitle_style")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    if isinstance(raw, dict):
        return raw
    return {"fontSize": 44, "color": "#FFFFFF", "position": "bottom", "stroke": 3}


def _preferred_title(task: PipelineTask, ctx: dict) -> str:
    """标题取值优先级（不截断）：上游 LLM 标题 > 解析标题 > 任务名（占位名跳过）"""
    for candidate in (ctx.get("cover_title"), ctx.get("title"), task.title):
        text = str(candidate or "").strip()
        if text and text != "未命名任务":
            return text
    return ""


def _cover_text_from_ctx(task: PipelineTask, ctx: dict) -> str:
    """封面标题取值：LLM 标题优先并按封面版式截断，兜底口播文案截断"""
    text = _preferred_title(task, ctx)
    return text[:24] if text else (ctx.get("script") or "")[:18]


async def _compose_with_ctx(task: PipelineTask, ctx: dict) -> dict:
    """合成执行体：compose 首跑与 edit 步按剪辑台配置重合成共用（字幕样式/封面模板真链路）"""
    # 字幕双模式（C4）：TTS 字级时间戳优先，ASR 校准兜底；剪辑台显式关闭字幕时跳过烧录
    words = [] if ctx.get("subtitle_enabled") is False else (ctx.get("tts_words") or ctx.get("words") or [])
    bgm_mode = str(ctx.get("bgm_mode") or "off")
    bgm_volume = float(ctx.get("bgm_volume") or 0.0)
    inp = ComposeInput(
        video_key=ctx.get("avatar_video_key") or ctx.get("video_key") or "",
        audio_key=ctx.get("audio_key"),
        subtitle_words=[],  # 由 engine 转换
        subtitle_style=_subtitle_style_from_ctx(ctx),
        bgm_key=str(ctx.get("bgm_key") or "") or None if bgm_mode == "custom" else None,
        bgm_mode=bgm_mode,
        cover_text=_cover_text_from_ctx(task, ctx),
        cover_template=str(ctx.get("cover_template") or "bold-bottom"),
        bgm_volume=max(0.0, min(bgm_volume, 1.0)),
        randomize=task.randomize,
    )
    from app.providers.base import WordTs

    inp.subtitle_words = [WordTs(word=w["word"], start=w["start"], end=w["end"]) for w in words]
    result, provider = await registry.run_with_fallback(
        "compose", registry.compose_chain, "compose", inp, trace_id=task.trace_id, task_id=task.id
    )
    return await _guard_mock_result(
        task,
        "compose",
        provider,
        {
            "final_video_key": result.video_key,
            "cover_key": result.cover_key,
            "duration": result.duration,
            "quality": result.quality,
            "provider": provider,
        },
    )


async def step_edit(task: PipelineTask, ctx: dict) -> dict:
    """剪辑步（第⑥步）：剪辑台保存过配置时按配置真实重新合成；否则 auto 跳过、manual 人工确认"""
    has_config = bool(
        ctx.get("subtitle_style") or ctx.get("cover_template") or ctx.get("bgm_key") or ctx.get("bgm_mode") == "off"
    )
    if not has_config:
        if task.mode == "auto":
            return {"skipped": True, "note": "自动模式跳过剪辑步"}
        return {"edited": True, "note": "人工剪辑确认"}
    out = await _compose_with_ctx(task, ctx)
    out["edited"] = True
    out["note"] = "已按剪辑台配置重新合成"
    return out


async def step_publish(task: PipelineTask, ctx: dict) -> dict:
    platforms = json.loads(task.platforms_json or "[]")
    if not platforms:
        return {"skipped": True, "note": "未选择发布平台，成片已就绪"}
    quality = ctx.get("quality") or {}
    if not quality.get("passed"):
        raise RuntimeError("成片未通过质量检查，禁止发布")
    from app.modules.publish.service import publish_task_video

    async with SessionLocal() as db:
        job_ids = await publish_task_video(
            db,
            task.user_id,
            task.id,
            platforms,
            # 发布标题与封面取值优先级对齐（LLM 标题优先、口播文案兜底），不复用封面版式的 24/18 字截断；
            # 字数限长由 publish_task_video 按平台限长表（TITLE_LIMITS）统一截断，此处不预截
            title=_preferred_title(task, ctx) or str(ctx.get("script") or "") or task.title,
            video_key=ctx.get("final_video_key", ""),
            cover_key=ctx.get("cover_key", ""),
            scheduled_at=task.publish_at or None,
            render_version_id=str(ctx.get("render_version_id") or ""),
            render_version=int(ctx.get("render_version") or 0),
        )
    return {"publish_job_ids": job_ids}


STEP_RUNNERS = {
    "parse": step_parse,
    "asr": step_asr,
    "rewrite": step_rewrite,
    "voice": step_voice,
    "avatar": step_avatar,
    "compose": step_compose,
    "edit": step_edit,
    "publish": step_publish,
}


# ============ 引擎主循环 ============


async def _settle_and_activate_render(
    db: AsyncSession,
    task: PipelineTask,
    ctx: dict,
) -> bool:
    """外部发布前先完成结算并固化活动成片，避免未结算产物进入平台链路。"""
    if task.reservation_id:
        from app.modules.billing.service import (
            recover_reservation_after_failure,
            settle_reservation,
        )

        try:
            settled = await settle_reservation(db, task.reservation_id, task.id)
        except Exception:  # noqa: BLE001
            logger.exception(
                "task_billing_settlement_failed",
                task_id=task.id,
                user_id=task.user_id,
                reservation_id=task.reservation_id,
            )
            settled = 0
        if settled <= 0:
            recovered = await recover_reservation_after_failure(db, task.reservation_id, task.user_id)
            if recovered is not None and recovered.status == "settled":
                settled = recovered.actualPoints
            else:
                await db.refresh(task)
                task.status = "failed"
                task.error = "billing: settlement failed"
                await repo_save(db, task)
                await _emit(task)
                await _feed(task.user_id, "err", f"「{task.title}」积分结算失败")
                await notify_user(
                    db,
                    task.user_id,
                    "error",
                    f"任务结算失败：{task.title}",
                    "成片流程已执行，但积分结算未确认；冻结积分已进入恢复流程，请勿重复创建任务。",
                )
                return False
        task.quota_cost = float(settled)

    from app.modules.pipeline.service import ensure_active_render_version
    from app.modules.publish import repository as publish_repo

    active_render = await ensure_active_render_version(db, task)
    await publish_repo.pin_task_render_version(
        db,
        user_id=task.user_id,
        task_id=task.id,
        video_key=active_render.video_key,
        render_version_id=active_render.id,
        render_version=active_render.version,
    )
    await repo_save(db, task)
    ctx.clear()
    ctx.update(_load_artifacts(task))
    return True


async def _fail_task_when_gate_unavailable(task_id: str) -> None:
    """Turn an accepted message into a visible retryable failure instead of a stuck task."""
    async with SessionLocal() as db:
        task = await repo_get(db, task_id)
        if task is None or task.status != "pending":
            return
        task.status = "failed"
        task.error = "系统并发调度暂不可用，积分已恢复，请稍后重试"
        task.queue_message_id = ""
        user_id = task.user_id
        title = task.title
        reservation_id = task.reservation_id
        await repo_save(db, task)
        try:
            await notify_user(
                db,
                user_id,
                "error",
                f"任务调度失败：{title}",
                "任务未开始执行，冻结积分已恢复，请稍后重新报价重试。",
            )
            await _emit(task)
        finally:
            if reservation_id:
                from app.modules.billing.service import recover_reservation_after_failure

                await recover_reservation_after_failure(db, reservation_id, user_id)


@asynccontextmanager
async def _task_slot(task_id: str) -> AsyncIterator[bool]:
    try:
        lease = await _gate.acquire()
    except SemaphoreUnavailableError:
        logger.exception("pipeline_concurrency_gate_unavailable", task_id=task_id)
        await _fail_task_when_gate_unavailable(task_id)
        yield False
        return
    try:
        yield True
    finally:
        await lease.release()


async def run_task(task_id: str, from_step: str | None = None) -> None:
    """从断点续跑：跳过已 done 步骤；manual 模式每步完成挂起等待确认"""
    if task_id in _running:
        return
    _running.add(task_id)
    # 设置任务级上下文（供日志自动注入）
    task_id_var.set(task_id)
    try:
        async with _task_slot(task_id) as gate_ready:
            if not gate_ready:
                return
            async with SessionLocal() as db:
                task = await claim_for_run(db, task_id)
                if task is None:
                    return
                if settings.app_env != "dev" and not task.reservation_id:
                    task.status = "failed"
                    task.error = "billing: reservation required"
                    await repo_save(db, task)
                    logger.error(
                        "task_rejected_without_reservation",
                        task_id=task_id,
                        user_id=task.user_id,
                    )
                    await notify_user(
                        db,
                        task.user_id,
                        "error",
                        f"任务失败：{task.title}",
                        "缺少有效积分冻结，请重新报价后重试。",
                    )
                    return
                # 设置 trace_id 和 user_id 上下文
                trace_id_var.set(task.trace_id or "")
                user_id_var.set(task.user_id or "")
                steps = _load_steps(task)
                ctx = _load_artifacts(task)
                await _emit(task)

                start_idx = STEP_ORDER.index(from_step) if from_step in STEP_ORDER else 0
                # 重跑时重置该步及后续状态
                if from_step:
                    for i in range(start_idx, len(steps)):
                        steps[i].update({"status": "pending", "progress": 0, "message": "", "finishedAt": None})

                for i in range(start_idx, len(STEP_ORDER)):
                    step_name = STEP_ORDER[i]
                    st = steps[i]
                    billing_ready = False
                    if step_name == "publish":
                        billing_ready = await _settle_and_activate_render(db, task, ctx)
                        if not billing_ready:
                            return
                    if st["status"] == "done":
                        continue
                    # 用户取消检查（cancel 后及时退出，不再推进后续步骤）
                    await db.refresh(task)
                    if task.status == "canceled":
                        _dump_steps(task, steps)
                        await repo_save(db, task)
                        await _emit(task)
                        return
                    st.update({"status": "running", "startedAt": _now(), "progress": 10})
                    task.current_step = step_name
                    _dump_steps(task, steps)
                    await repo_save(db, task)
                    await _emit(task)

                    try:
                        step_start = time.perf_counter()
                        result = await STEP_RUNNERS[step_name](task, ctx)
                        step_ms = int((time.perf_counter() - step_start) * 1000)
                        # 步骤执行期间用户可能已取消：回读最新状态，避免本步落库把 canceled 覆盖回 running
                        await db.refresh(task)
                        skipped = bool(result.pop("skipped", False))
                        provider = result.pop("provider", "")
                        ctx.update({k: v for k, v in result.items() if not k.startswith("_")})
                        _dump_artifacts(task, ctx)

                        # 生产任务在创建时已冻结积分；开发环境无冻结任务只跑 Mock，不产生账单。
                        cost = 0.0
                        task.quota_cost += cost

                        st.update(
                            {
                                "status": "skipped" if skipped else "done",
                                "progress": 100,
                                "provider": provider,
                                "quotaCost": cost,
                                "message": result.get("note", ""),
                                "artifacts": {k: str(v)[:200] for k, v in result.items()},
                                "durationMs": step_ms,
                                "finishedAt": _now(),
                            }
                        )
                        # 步骤完成性能日志（§10.6.9 Phase 3 B#2）
                        logger.info(
                            "step_done",
                            task_id=task_id,
                            step=step_name,
                            provider=provider,
                            duration_ms=step_ms,
                            skipped=skipped,
                        )
                    except Exception as e:  # noqa: BLE001
                        from app.providers.base import ProviderOutcomeUnknown

                        outcome_unknown = isinstance(e, ProviderOutcomeUnknown)
                        # 步骤失败：记录 ERROR + 结构化字段（§10.6.8-A #3）
                        logger.error(
                            "step_failed",
                            task_id=task_id,
                            step=step_name,
                            provider=st.get("provider", ""),
                            error=str(e)[:200],
                            trace_id=task.trace_id,
                            user_id=task.user_id,
                        )
                        if task.reservation_id and not outcome_unknown and not billing_ready:
                            from app.modules.billing.service import release_reservation

                            await release_reservation(db, task.reservation_id, task.user_id)
                        step_ms = int((time.perf_counter() - step_start) * 1000)
                        if step_name == "publish" and billing_ready:
                            safe_error = "成片已完成，但发布任务创建失败；请前往发布管理重新提交"
                            st.update(
                                {
                                    "status": "failed",
                                    "message": safe_error,
                                    "durationMs": step_ms,
                                    "finishedAt": _now(),
                                }
                            )
                            task.status = "done"
                            task.current_step = ""
                            task.error = ""
                            _dump_steps(task, steps)
                            await repo_save(db, task)
                            await _emit(task)
                            await _feed(task.user_id, "info", f"「{task.title}」成片完成，发布任务待重新提交")
                            await notify_user(
                                db,
                                task.user_id,
                                "warn",
                                f"成片已完成：{task.title}",
                                "发布任务创建失败，成片与积分结算均已保留；请前往发布管理重新提交。",
                            )
                            logger.warning(
                                "pipeline_publish_setup_failed",
                                task_id=task_id,
                                user_id=task.user_id,
                            )
                            return
                        safe_error = (
                            "外部服务提交结果未知，已暂停自动重试并保留积分冻结，等待管理员对账"
                            if outcome_unknown
                            else public_error_message(e)
                        )
                        st.update(
                            {
                                "status": "reconciliation_required" if outcome_unknown else "failed",
                                "message": safe_error,
                                "durationMs": step_ms,
                                "finishedAt": _now(),
                            }
                        )
                        task.status = "reconciliation_required" if outcome_unknown else "failed"
                        task.error = safe_error
                        _dump_steps(task, steps)
                        await repo_save(db, task)
                        await _emit(task)
                        await _feed(task.user_id, "err", f"「{task.title}」{step_name} 步失败：{safe_error}")
                        await notify_user(
                            db,
                            task.user_id,
                            "error",
                            (f"任务等待人工对账：{task.title}" if outcome_unknown else f"任务失败：{task.title}"),
                            (
                                f"步骤={step_name}；耗时={step_ms}ms；{safe_error}。"
                                if outcome_unknown
                                else f"步骤={step_name}；耗时={step_ms}ms；{safe_error}；可重新报价后从该步骤重试。"
                            ),
                        )
                        # 任务最终失败：记录 ERROR
                        logger.error(
                            "task_failed",
                            task_id=task_id,
                            failed_step=step_name,
                            error=str(e)[:200],
                            trace_id=task.trace_id,
                            user_id=task.user_id,
                        )
                        return

                    _dump_steps(task, steps)
                    await repo_save(db, task)
                    await _emit(task)

                    # 步骤执行期间收到取消：保留 canceled 状态并立即停止推进
                    if task.status == "canceled":
                        logger.info("task_canceled_midstep", task_id=task_id, step=step_name)
                        await _feed(task.user_id, "info", f"「{task.title}」已取消，流程停止")
                        return

                    # manual 模式：每步完成暂停（F-405 单步干预）
                    if task.mode == "manual" and step_name != "publish":
                        task.status = "waiting_confirm"
                        await repo_save(db, task)
                        await _emit(task)
                        await _feed(task.user_id, "info", f"「{task.title}」{step_name} 步完成，等待确认")
                        return

                task.status = "done"
                task.current_step = ""
                await repo_save(db, task)
                await _emit(task)
                await _feed(task.user_id, "ok", f"「{task.title}」全流程完成")
                await notify_user(
                    db,
                    task.user_id,
                    "info",
                    f"全流程完成：{task.title}",
                    (
                        f"积分={task.quota_cost:g}；成片={ctx.get('final_video_key') or '未生成'}；"
                        f"发布任务={','.join(ctx.get('publish_job_ids') or []) or '无'}。"
                    ),
                )
                logger.info("task_done", task_id=task_id, user_id=task.user_id, quota_cost=task.quota_cost)
    finally:
        _running.discard(task_id)


def schedule_run(task_id: str, from_step: str | None = None) -> str:
    """把流水线投递到 Redis/Dramatiq 持久队列。"""
    from app.workers.tasks import run_pipeline_task

    message = run_pipeline_task.send(task_id, from_step)
    return message.message_id
