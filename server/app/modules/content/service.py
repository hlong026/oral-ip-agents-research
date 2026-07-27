"""
content 业务编排（F-101~F-106）
降级链：自建解析 → 第三方解析 API → 手动上传/粘贴文案（C2，全链路 100% 可用）
链接转写策略：优先转写 Douyidou 音频直链，音频缺失时转写视频，平台 text 仅兜底
ASR 智能分流：短音频(≤5min)走Flash同步 / 长音频走异步轮询
日志：LLM 调用完成（§10.6.8-B #3）
"""

import base64
import ipaddress
import json
import time
from collections.abc import Awaitable, Callable
from datetime import UTC
from pathlib import Path
from urllib.parse import urlparse

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.dynamic_config import get_config_int
from app.core.logging import get_logger
from app.core.storage import StorageConfigurationError, get_accessible_url, read_bytes, save_bytes, size
from app.core.white_label import public_model_name
from app.providers.base import ProviderError
from app.providers.base import is_mock_provider as _is_mock_provider
from app.providers.douyidou import DouyidouParser, DouyidouParseResult
from app.providers.duration_probe import MediaProcessingError, extract_audio_bytes, extract_audio_key, probe_duration
from app.providers.registry import registry
from app.providers.url_resolver import resolve_input

from . import repository as repo
from .models import Script, ScriptVersion
from .prompts import PROMPT_VERSION
from .schemas import (
    BatchRewriteItemOut,
    BatchRewriteOut,
    ParseOut,
    RewriteOut,
    ScriptOut,
    ScriptVersionOut,
    SimilarityOut,
    SpanOut,
    TranscriptOut,
    WordTsOut,
)

logger = get_logger("oral.content")
settings = get_settings()
_VARIANT_STRATEGIES = (
    ("强化开头钩子，表达稳健", 0.7),
    ("调整叙事节奏，增加口语变化", 0.9),
    ("转换表达视角，提升创意差异", 1.1),
    ("强化案例与细节，减少抽象表述", 0.8),
    ("压缩冗余内容，突出行动引导", 1.0),
)
_UPLOAD_MEDIA_TYPES = {
    ".aac": "audio/aac",
    ".avi": "video/x-msvideo",
    ".m4a": "audio/mp4",
    ".mkv": "video/x-matroska",
    ".mov": "video/quicktime",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".wav": "audio/wav",
}
_MAX_ASR_DATA_URI_BYTES = 20 * 1024 * 1024
_PROBE_RESULT_TTL_SECONDS = 60.0
_probe_result_cache: dict[str, tuple[float, DouyidouParseResult]] = {}


def _cache_probe_result(url: str, result: DouyidouParseResult) -> None:
    now = time.monotonic()
    expired = [
        key for key, (cached_at, _) in _probe_result_cache.items() if now - cached_at > _PROBE_RESULT_TTL_SECONDS
    ]
    for key in expired:
        _probe_result_cache.pop(key, None)
    _probe_result_cache[url] = (now, result)


def _recent_probe_result(url: str) -> DouyidouParseResult | None:
    cached = _probe_result_cache.get(url)
    if cached is None:
        return None
    cached_at, result = cached
    if time.monotonic() - cached_at > _PROBE_RESULT_TTL_SECONDS:
        _probe_result_cache.pop(url, None)
        return None
    return result


def _is_public_media_url(value: str) -> bool:
    parsed = urlparse(value)
    hostname = parsed.hostname or ""
    if parsed.scheme not in {"http", "https"} or not hostname:
        return False
    try:
        return ipaddress.ip_address(hostname).is_global
    except ValueError:
        return hostname != "localhost" and not hostname.endswith((".local", ".internal"))


def _media_data_uri(filename: str, data: bytes) -> str:
    media_type = _UPLOAD_MEDIA_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream")
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


async def _embedded_asr_input(filename: str, data: bytes) -> str:
    media_input = _media_data_uri(filename, data)
    if len(media_input) <= _MAX_ASR_DATA_URI_BYTES:
        return media_input
    audio = await extract_audio_bytes(data, Path(filename).suffix.lower())
    return _media_data_uri("audio.mp3", audio)


async def _embedded_asr_input_from_key(filename: str, key: str) -> str:
    """小文件直接内嵌；大文件从存储流式提取压缩音轨。"""
    raw_limit = _MAX_ASR_DATA_URI_BYTES * 3 // 4
    if await size(key) <= raw_limit:
        return await _embedded_asr_input(filename, await read_bytes(key))
    return _media_data_uri("audio.mp3", await extract_audio_key(key))


async def parse_url(
    db: AsyncSession,
    user_id: str,
    url: str,
    persona_id: str | None,
    verified_duration_seconds: float | None = None,
    require_verified_duration: bool = False,
) -> ParseOut:
    """链接解析 → 音频优先 ASR → 落文案资产（抖/快/红书；视频号走文件上传入口）"""
    # URL/ID 识别与标准化
    resolved = resolve_input(url)
    logger.info(f"解析输入: platform={resolved.platform.value}, is_id={resolved.is_id}, url={resolved.url[:80]}")

    # 尝试 Douyidou 完整解析（获取文案+视频直链）
    douyidou_result = _recent_probe_result(resolved.url)
    if douyidou_result is not None:
        logger.info("复用时长探测阶段的 Douyidou 解析结果，避免重复请求上游")
    elif await registry.provider_enabled("douyidou"):
        try:
            parser = DouyidouParser()
            douyidou_result = await parser.parse_url_full(resolved.url)
        except Exception as e:
            logger.warning(f"Douyidou 完整解析失败，走降级链: {e}")

    # 平台 text 往往只是发布说明；完整口播必须优先从原始音频识别。
    audio_url = next(
        (
            value
            for value in (douyidou_result.audio if douyidou_result else [])
            if isinstance(value, str) and _is_public_media_url(value)
        ),
        None,
    )
    video_url = douyidou_result.video_url if douyidou_result else None
    platform = douyidou_result.platform if douyidou_result else resolved.platform.value
    title = douyidou_result.title if douyidou_result else ""
    cover = douyidou_result.cover if douyidou_result else None

    if not audio_url and not video_url:
        # 降级链兜底（Mock 产出的是占位视频，禁止流入真实转写，否则会静默落库假文案）
        parse_result, parse_provider = await registry.run_with_fallback(
            "parse", registry.parse_chain, "parse_url", resolved.url
        )
        if _is_mock_provider(parse_provider):
            logger.warning(f"链接解析降级至 {parse_provider}，占位视频不可用于真实转写，转入文本兜底/失败提示")
        else:
            video_url = parse_result.video_key
            platform = parse_result.platform
            title = parse_result.title

    media_url = audio_url or video_url
    if not media_url and douyidou_result and douyidou_result.text:
        logger.warning("音视频直链不可用，降级使用平台发布文本")
        return await _save_text_result(db, user_id, persona_id, resolved.url, douyidou_result)

    if not media_url:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "LINK_SOURCE_UNAVAILABLE",
                "message": "链接暂时无法访问，请粘贴正文或上传本地文件继续",
                "fallbacks": ["paste_text", "upload_file"],
            },
        )

    known_dur = douyidou_result.duration_sec if douyidou_result else None
    duration_sec = verified_duration_seconds or await probe_duration(
        media_url,
        platform=platform,
        known_duration=known_dur,
    )
    if require_verified_duration and duration_sec is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "MEDIA_DURATION_UNVERIFIED",
                "message": "无法验证链接媒体时长，请上传本地文件后重试",
            },
        )
    logger.info(f"ASR 分流决策: duration={duration_sec}, threshold={300}s")

    logger.info(f"ASR 媒体选择: source={'audio' if audio_url else 'video'}")

    # ASR 转写（优先直传音频URL，按时长智能分流）
    tr, provider_name = await registry.run_with_fallback(
        "asr", registry.asr_chain, "transcribe", media_url, duration_sec=duration_sec
    )
    if _is_mock_provider(provider_name):
        # 真实媒体被 Mock ASR 兜底 = 转写链路全挂，占位文案绝不能当真实转写结果
        logger.warning(f"ASR 降级至 {provider_name}，拒绝将占位文案当作真实转写结果")
        if douyidou_result and douyidou_result.text:
            logger.warning("改用平台发布文本兜底")
            return await _save_text_result(db, user_id, persona_id, resolved.url, douyidou_result)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "ASR_FAILED",
                "message": "语音转写暂时不可用，请稍后重试、粘贴正文或上传本地文件",
                "fallbacks": ["paste_text", "upload_file"],
            },
        )
    transcript = TranscriptOut(
        text=tr.text,
        duration=tr.duration,
        language=tr.language,
        words=[WordTsOut(word=w.word, start=w.start, end=w.end) for w in tr.words],
    )
    script = await _create_script_with_source_version(
        db,
        user_id=user_id,
        persona_id=persona_id or "",
        title=title or "解析文案",
        source_url=resolved.url,
        platform=platform,
        original_text=tr.text,
        words_json=json.dumps([{"word": w.word, "start": w.start, "end": w.end} for w in tr.words], ensure_ascii=False),
    )
    return ParseOut(
        transcript=transcript,
        degraded=False,
        inputType="link",
        sourceStatus="ready",
        platform=platform,
        title=title,
        scriptId=script.id,
        cover=cover,
        author=douyidou_result.author if douyidou_result else None,
    )


async def _save_text_result(
    db: AsyncSession, user_id: str, persona_id: str | None, source_url: str, result: DouyidouParseResult
) -> ParseOut:
    """音视频不可用时，将 Douyidou 平台文本作为最后兜底（标记 degraded 供前端提示）。"""
    text = result.text or ""
    script = await _create_script_with_source_version(
        db,
        user_id=user_id,
        persona_id=persona_id or "",
        title=result.title or text[:20],
        source_url=source_url,
        platform=result.platform,
        original_text=text,
        words_json="[]",
    )
    logger.info(f"平台文本兜底命中: platform={result.platform}, text_len={len(text)}")
    return ParseOut(
        transcript=TranscriptOut(text=text, words=[], duration=0, language="zh"),
        degraded=True,
        inputType="link",
        sourceStatus="ready",
        platform=result.platform,
        title=result.title,
        scriptId=script.id,
        cover=result.cover,
        author=result.author or None,
    )


async def parse_by_id(
    db: AsyncSession,
    user_id: str,
    video_id: str,
    platform: str,
    persona_id: str | None,
    verified_duration_seconds: float | None = None,
    require_verified_duration: bool = False,
) -> ParseOut:
    """通过视频ID + 平台解析（内部拼接URL后走统一链路）"""
    if platform == "douyin":
        url = f"https://www.douyin.com/video/{video_id}"
    elif platform == "xiaohongshu":
        url = f"https://www.xiaohongshu.com/explore/{video_id}"
    else:
        url = video_id  # 透传
    return await parse_url(
        db,
        user_id,
        url,
        persona_id,
        verified_duration_seconds,
        require_verified_duration,
    )


async def probe_url_duration(url: str, *, required: bool) -> float | None:
    """在报价前解析直链，并只返回供应商值或 ffprobe 验证值。"""
    resolved = resolve_input(url)
    result = _recent_probe_result(resolved.url)
    fallback_chain = registry.parse_chain
    if result is None and await registry.provider_enabled("douyidou"):
        fallback_chain = [provider for provider in registry.parse_chain if provider.name != "douyidou"]
        try:
            result = await DouyidouParser().parse_url_full(resolved.url)
        except Exception as exc:
            logger.warning(f"Douyidou 时长探测失败，走降级链: {exc}")

    video_url = result.video_url if result else None
    platform = result.platform if result else resolved.platform.value
    if not video_url:
        try:
            parsed, _ = await registry.run_with_fallback(
                "parse",
                fallback_chain,
                "parse_url",
                resolved.url,
            )
            video_url = parsed.video_key
            platform = parsed.platform
        except Exception as exc:
            logger.warning(f"链接直链解析失败，无法探测时长: {exc}")

    duration = await probe_duration(
        video_url or "",
        platform=platform,
        known_duration=result.duration_sec if result else None,
    )
    if required and duration is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "MEDIA_DURATION_UNVERIFIED",
                "message": "无法验证链接媒体时长，请上传本地文件后重试",
            },
        )
    if result is not None:
        _cache_probe_result(resolved.url, result)
    return duration


async def parse_upload(
    db: AsyncSession,
    user_id: str,
    filename: str,
    data: bytes | None,
    persona_id: str | None,
    duration_seconds: float | None = None,
    storage_key: str | None = None,
) -> ParseOut:
    """手动上传降级（视频号等平台，C2 兖底）"""
    if storage_key:
        key = storage_key
    elif data is not None:
        key = await save_bytes("uploads", filename, data)
    else:
        raise ValueError("parse_upload requires data or storage_key")
    try:
        threshold = await get_config_int("asr_flash_threshold_sec", 300)
        if duration_seconds is not None and duration_seconds <= threshold:
            accessible_url = await get_accessible_url(key, require_public=False)
            media_input = (
                accessible_url
                if _is_public_media_url(accessible_url)
                else (
                    await _embedded_asr_input(filename, data)
                    if data is not None
                    else await _embedded_asr_input_from_key(filename, key)
                )
            )
        else:
            media_input = await get_accessible_url(key, require_public=True)
    except StorageConfigurationError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "MEDIA_PUBLIC_URL_REQUIRED",
                "message": "媒体处理服务暂不可用，请联系管理员检查存储配置",
            },
        ) from exc
    except MediaProcessingError as exc:
        logger.warning("upload_audio_extraction_failed", filename=filename, error=str(exc)[:300])
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "MEDIA_AUDIO_EXTRACTION_FAILED",
                "message": "无法从上传文件提取有效音轨，请检查文件后重试",
            },
        ) from exc
    try:
        tr, asr_provider = await registry.run_with_fallback(
            "asr", registry.asr_chain, "transcribe", media_input, duration_sec=duration_seconds
        )
    except ProviderError as exc:
        logger.warning(
            "upload_asr_failed",
            filename=filename,
            error=str(exc)[:200],
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "ASR_FAILED",
                "message": "语音转写暂时不可用，请重试上传或直接粘贴正文",
                "fallbacks": ["paste_text", "retry_upload"],
            },
        ) from exc
    if _is_mock_provider(asr_provider):
        # 上传的是真实媒体文件，Mock 占位文案不能当作转写结果落库
        logger.warning(f"上传转写降级至 {asr_provider}，拒绝占位文案")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "ASR_FAILED",
                "message": "语音转写暂时不可用，请重试上传或直接粘贴正文",
                "fallbacks": ["paste_text", "retry_upload"],
            },
        )
    script = await _create_script_with_source_version(
        db,
        user_id=user_id,
        persona_id=persona_id or "",
        title=filename,
        platform="upload",
        original_text=tr.text,
        words_json=json.dumps([{"word": w.word, "start": w.start, "end": w.end} for w in tr.words], ensure_ascii=False),
    )
    return ParseOut(
        transcript=TranscriptOut(
            text=tr.text,
            duration=tr.duration,
            language=tr.language,
            words=[WordTsOut(word=w.word, start=w.start, end=w.end) for w in tr.words],
        ),
        degraded=False,
        inputType="upload",
        sourceStatus="ready",
        platform="upload",
        title=filename,
        scriptId=script.id,
    )


async def parse_text(
    db: AsyncSession,
    user_id: str,
    text: str,
    persona_id: str | None,
) -> ParseOut:
    """正文粘贴是正式输入，不经过链接解析或 ASR。"""
    normalized = text.strip()
    if not normalized:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "TEXT_REQUIRED", "message": "请粘贴正文后重试"},
        )
    script = await _create_script_with_source_version(
        db,
        user_id=user_id,
        persona_id=persona_id or "",
        title=normalized[:20],
        source_url="",
        platform="manual",
        original_text=normalized,
        words_json="[]",
    )
    return ParseOut(
        transcript=TranscriptOut(text=normalized, words=[], duration=0, language="zh"),
        degraded=False,
        inputType="text",
        sourceStatus="ready",
        platform="manual",
        title=script.title,
        scriptId=script.id,
    )


async def rewrite(
    db: AsyncSession,
    user_id: str,
    text: str,
    intensity: str,
    prompt: str | None,
    script_id: str | None,
    progress_callback: Callable[[int, str], Awaitable[None]] | None = None,
) -> RewriteOut:
    """三阶段IP仿写引擎：结构拆解 → IP化大纲 → 全文生成+校验闭环"""
    start_time = time.perf_counter()
    # 人设引擎注入（F-701）
    persona_ctx = ""
    persona = None
    if script_id:
        s = await repo.get(db, script_id, user_id)
        if s and s.persona_id:
            from app.modules.ipasset.repository import get as get_persona

            persona = await get_persona(db, s.persona_id, user_id)
            if persona:
                from app.modules.ipasset.service import persona_prompt_context

                persona_ctx = persona_prompt_context(persona)

    # 如果没有通过 script_id 找到 persona，尝试用户活跃 persona
    if not persona_ctx:
        from app.modules.ipasset.repository import get as get_persona
        from app.modules.ipasset.service import get_active_persona_id, persona_prompt_context

        active_id = await get_active_persona_id(db, user_id)
        if active_id:
            persona = await get_persona(db, active_id, user_id)
            if persona:
                persona_ctx = persona_prompt_context(persona)

    llm = registry.get("llm")
    provider_name = llm.name
    duration = persona.video_duration if persona else 60
    taboo_words = "、".join(json.loads(persona.taboo_words or "[]")) if persona else "无"
    cta_style = persona.cta_style if persona else "关注收藏"
    avoid_topics = json.loads(persona.avoid_topics or "[]") if persona else []
    custom_prompt = (prompt or "").strip()

    # ---- Light 模式：单步人设润色 ----
    if intensity == "light":
        if progress_callback:
            await progress_callback(35, "正在结合当前 IP 润色文案")
        if persona_ctx:
            light_persona_ctx = persona_ctx
            if custom_prompt:
                light_persona_ctx += f"\n\n【用户自定义改写要求】\n{custom_prompt}"
            result = await llm.polish_light(text, light_persona_ctx)
        else:
            result, provider_name = await registry.run_with_fallback(
                "llm", registry.llm_chain, "rewrite", text, "light", custom_prompt or None
            )
        # 禁忌词校验
        result, passed = _validate_taboo(result, taboo_words, avoid_topics)
        if script_id:
            await _append_generated_version(db, user_id, script_id, result, provider_name, 0.0)
        return RewriteOut(text=result, validationPassed=passed)

    # ---- Stage 1: 结构拆解 ----
    if progress_callback:
        await progress_callback(20, "正在分析原文结构")
    mode = "theme" if intensity == "theme" else "full"
    structure = await llm.analyze_structure(text, mode=mode)

    # ---- Stage 2: IP化大纲 ----
    if progress_callback:
        await progress_callback(45, "正在生成 IP 化大纲")
    outline = await llm.generate_outline(structure, persona_ctx, intensity, duration)

    # ---- Stage 3: 全文生成 ----
    if progress_callback:
        await progress_callback(65, "正在生成完整改写文案")
    constraints = {
        "duration": duration,
        "cta_style": cta_style or "关注收藏",
        "taboo_words": taboo_words or "无",
        "extra_prompt": custom_prompt,
    }
    result = await llm.generate_script(outline, persona_ctx, constraints)

    # ---- 校验闭环：禁忌词 + 去重检测（最多2轮再改写） ----
    if progress_callback:
        await progress_callback(82, "正在执行禁忌词和重复度校验")
    validation_passed = True
    final_score = 0.0
    for _round in range(2):
        issues = []
        # 禁忌词检测
        found_taboo = [w for w in (json.loads(persona.taboo_words or "[]") if persona else []) if w in result]
        if found_taboo:
            issues.append(f"包含禁忌词：{'、'.join(found_taboo)}")
        # 回避话题检测
        found_avoid = [t for t in avoid_topics if t in result]
        if found_avoid:
            issues.append(f"涉及回避话题：{'、'.join(found_avoid)}")
        # 去重检测
        sim_result, _ = await registry.run_with_fallback("llm", registry.llm_chain, "check_similarity", result, text)
        final_score = sim_result.score
        if sim_result.score > 60:
            issues.append(f"与原文相似度偏高（{sim_result.score:.0f}分），需降低重复度")
            if sim_result.duplicated_spans:
                spans_text = "、".join(s["text"][:20] for s in sim_result.duplicated_spans[:3])
                issues.append(f"高重复片段：{spans_text}")

        if not issues:
            break
        validation_passed = False
        # 带反馈再改写
        result = await llm.validation_rewrite(result, persona_ctx, "\n".join(issues))
    else:
        # 循环耗尽（文本被重写过），重新检测最终相似度
        sim_result, _ = await registry.run_with_fallback("llm", registry.llm_chain, "check_similarity", result, text)
        final_score = sim_result.score
        validation_passed = sim_result.score <= 60

    # 落库
    if script_id:
        await _append_generated_version(db, user_id, script_id, result, provider_name, final_score)

    # 仿写完成：记录 INFO（§10.6.8-B #3）
    duration_ms = int((time.perf_counter() - start_time) * 1000)
    logger.info(
        "rewrite_done",
        user_id=user_id,
        intensity=intensity,
        duration_ms=duration_ms,
        text_len=len(result),
        similarity=final_score,
    )

    return RewriteOut(
        text=result,
        structure=structure,
        outline=outline,
        similarity=final_score,
        validationPassed=validation_passed,
    )


async def batch_rewrite(
    db: AsyncSession,
    user_id: str,
    text: str,
    intensity: str,
    count: int,
    prompt: str | None,
    script_id: str | None,
) -> BatchRewriteOut:
    """共享一次结构与大纲分析，生成 2~5 条可排序候选文案。"""
    if not 2 <= count <= 5:
        raise ValueError("count 必须在 2 到 5 之间")

    persona = None
    persona_ctx = ""
    if script_id:
        script = await repo.get(db, script_id, user_id)
        if script and script.persona_id:
            from app.modules.ipasset.repository import get as get_persona

            persona = await get_persona(db, script.persona_id, user_id)
    if persona is None:
        from app.modules.ipasset.repository import get as get_persona
        from app.modules.ipasset.service import get_active_persona_id

        active_id = await get_active_persona_id(db, user_id)
        if active_id:
            persona = await get_persona(db, active_id, user_id)
    if persona:
        from app.modules.ipasset.service import persona_prompt_context

        persona_ctx = persona_prompt_context(persona)

    mode = "theme" if intensity == "theme" else "full"
    structure, _ = await registry.run_with_fallback(
        "llm",
        registry.llm_chain,
        "analyze_structure",
        text,
        mode=mode,
    )
    duration = persona.video_duration if persona else 60
    outline, _ = await registry.run_with_fallback(
        "llm",
        registry.llm_chain,
        "generate_outline",
        structure,
        persona_ctx,
        intensity,
        duration,
    )
    taboo_words = "、".join(json.loads(persona.taboo_words or "[]")) if persona else "无"
    constraints = {
        "duration": duration,
        "cta_style": persona.cta_style if persona else "关注收藏",
        "taboo_words": taboo_words,
        "extra_prompt": prompt or "",
    }

    candidates: list[tuple[BatchRewriteItemOut, str]] = []
    for strategy, temperature in _VARIANT_STRATEGIES[:count]:
        candidate, provider_name = await registry.run_with_fallback(
            "llm",
            registry.llm_chain,
            "generate_script_variant",
            outline,
            persona_ctx,
            constraints,
            temperature,
            strategy,
        )
        similarity_result, _ = await registry.run_with_fallback(
            "llm",
            registry.llm_chain,
            "check_similarity",
            candidate,
            text,
        )
        candidates.append(
            (
                BatchRewriteItemOut(
                    text=candidate,
                    similarity=similarity_result.score,
                    strategy=strategy,
                    providerName=public_model_name(provider_name),
                ),
                provider_name,
            )
        )

    candidates.sort(key=lambda candidate: candidate[0].similarity)
    items = [item for item, _provider_name in candidates]
    if script_id and candidates:
        best, best_provider_name = candidates[0]
        await _append_generated_version(db, user_id, script_id, best.text, best_provider_name, best.similarity)
    logger.info(
        "batch_rewrite_done",
        user_id=user_id,
        count=count,
        best_similarity=items[0].similarity,
    )
    return BatchRewriteOut(items=items, structure=structure, outline=outline)


def _validate_taboo(text: str, taboo_words: str, avoid_topics: list[str]) -> tuple[str, bool]:
    """禁忌词简单检测（light模式用，不触发再改写）"""
    words = [w for w in taboo_words.split("、") if w and w in text]
    topics = [t for t in avoid_topics if t in text]
    return text, not words and not topics


async def similarity(text: str) -> SimilarityOut:
    """去重度检测（F-106：Embedding + n-gram 双指标）"""
    start_time = time.perf_counter()
    result, _ = await registry.run_with_fallback("llm", registry.llm_chain, "check_similarity", text)
    # 去重检测完成：记录 INFO（§10.6.8-B #3）
    duration_ms = int((time.perf_counter() - start_time) * 1000)
    logger.info("similarity_done", duration_ms=duration_ms, score=result.score)
    return SimilarityOut(
        score=result.score,
        duplicatedSpans=[SpanOut(**s) for s in result.duplicated_spans],
    )


async def topics(keyword: str) -> list[str]:
    start_time = time.perf_counter()
    result, _ = await registry.run_with_fallback("llm", registry.llm_chain, "generate_topics", keyword, 5)
    # 选题生成完成：记录 INFO（§10.6.8-B #3）
    duration_ms = int((time.perf_counter() - start_time) * 1000)
    logger.info("topics_done", keyword=keyword[:50], count=len(result), duration_ms=duration_ms)
    return result


async def create_script(
    db: AsyncSession, user_id: str, persona_id: str | None, title: str, text: str, platform: str, topic: str | None
) -> ScriptOut:
    """手动创建文案资产（选题生成 / 直接编写入口），与解析产物同构"""
    script = await _create_script_with_source_version(
        db,
        user_id=user_id,
        persona_id=persona_id or "",
        title=title or (topic or text[:20] or "手动文案"),
        source_url="",
        platform=platform,
        original_text=text,
        words_json="[]",
    )
    return to_out(script)


async def update_script(
    db: AsyncSession,
    user_id: str,
    script_id: str,
    *,
    title: str,
    text: str,
) -> ScriptOut:
    script = await repo.get_for_update(db, script_id, user_id)
    if not script:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "文案不存在"})
    clean_title = title.strip()
    clean_text = text.strip()
    if script.title == clean_title and (script.rewritten_text or script.original_text) == clean_text:
        return to_out(script)
    script.title = clean_title
    script.rewritten_text = clean_text
    script.current_version += 1
    script.model_name = "human"
    script.prompt_version = "manual"
    try:
        await repo.append_version(
            db,
            script,
            kind="manual_edit",
            text=script.rewritten_text,
            model_name="human",
            prompt_version="manual",
            commit=False,
        )
        await db.commit()
        await db.refresh(script)
    except BaseException:
        await db.rollback()
        raise
    return to_out(script)


async def list_script_versions(db: AsyncSession, user_id: str, script_id: str) -> list[ScriptVersionOut]:
    if not await repo.get(db, script_id, user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "文案不存在"})
    return [version_to_out(version) for version in await repo.list_versions(db, script_id, user_id)]


async def list_scripts(db: AsyncSession, user_id: str) -> list[ScriptOut]:
    items = await repo.list_by_user(db, user_id)
    return [to_out(s) for s in items]


async def get_script(db: AsyncSession, user_id: str, script_id: str) -> ScriptOut:
    s = await repo.get(db, script_id, user_id)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "文案不存在"})
    return to_out(s)


def to_out(s: Script) -> ScriptOut:
    return ScriptOut(
        id=s.id,
        title=s.title,
        sourceUrl=s.source_url,
        platform=s.platform,
        originalText=s.original_text,
        rewrittenText=s.rewritten_text,
        similarityScore=s.similarity_score,
        currentVersion=s.current_version,
        modelName=public_model_name(s.model_name),
        promptVersion=s.prompt_version,
        status=s.status,
        createdAt=s.created_at.astimezone(UTC).isoformat(),
    )


def version_to_out(version: ScriptVersion) -> ScriptVersionOut:
    return ScriptVersionOut(
        id=version.id,
        version=version.version,
        kind=version.kind,
        text=version.text,
        modelName=public_model_name(version.model_name),
        promptVersion=version.prompt_version,
        createdAt=version.created_at.astimezone(UTC).isoformat(),
    )


async def _create_script_with_source_version(db: AsyncSession, **fields) -> Script:
    script = await repo.create(
        db,
        commit=False,
        current_version=1,
        model_name="source",
        prompt_version="source",
        **fields,
    )
    try:
        await repo.append_version(
            db,
            script,
            kind="source",
            text=script.original_text,
            model_name="source",
            prompt_version="source",
            commit=False,
        )
        await db.commit()
        await db.refresh(script)
    except BaseException:
        await db.rollback()
        raise
    return script


async def _append_generated_version(
    db: AsyncSession,
    user_id: str,
    script_id: str,
    text: str,
    provider_name: str,
    similarity_score: float,
) -> None:
    script = await repo.get_for_update(db, script_id, user_id)
    if not script:
        return
    script.rewritten_text = text
    script.similarity_score = similarity_score
    script.current_version += 1
    script.model_name = provider_name
    script.prompt_version = PROMPT_VERSION
    try:
        await repo.append_version(
            db,
            script,
            kind="model_rewrite",
            text=text,
            model_name=provider_name,
            prompt_version=PROMPT_VERSION,
            commit=False,
        )
        await db.commit()
        await db.refresh(script)
    except BaseException:
        await db.rollback()
        raise
