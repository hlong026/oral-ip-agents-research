"""
content 业务编排（F-101~F-106）
降级链：自建解析 → 第三方解析 API → 手动上传/粘贴文案（C2，全链路 100% 可用）
文案优先策略：Douyidou 返回 text 非空时直接使用（跳过ASR，零成本）
ASR 智能分流：短音频(≤5min)走Flash同步 / 长音频走异步轮询
日志：LLM 调用完成（§10.6.8-B #3）
"""
import json
import time
from datetime import UTC

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.storage import save_bytes
from app.providers.douyidou import DouyidouParser, DouyidouParseResult
from app.providers.duration_probe import probe_duration
from app.providers.registry import registry
from app.providers.url_resolver import Platform, resolve_input

from . import repository as repo
from .models import Script
from .schemas import ParseOut, ScriptOut, SimilarityOut, SpanOut, TranscriptOut, WordTsOut

logger = get_logger("oral.content")


async def parse_url(db: AsyncSession, user_id: str, url: str, persona_id: str | None) -> ParseOut:
    """链接解析 → 文案优先 / ASR 转写 → 落文案资产（抖/快/红书；视频号走文件上传入口）"""
    # URL/ID 识别与标准化
    resolved = resolve_input(url)
    logger.info(f"解析输入: platform={resolved.platform.value}, is_id={resolved.is_id}, url={resolved.url[:80]}")

    # 尝试 Douyidou 完整解析（获取文案+视频直链）
    douyidou_result: DouyidouParseResult | None = None
    try:
        parser = DouyidouParser()
        douyidou_result = await parser.parse_url_full(resolved.url)
    except Exception as e:
        logger.warning(f"Douyidou 完整解析失败，走降级链: {e}")

    # 文案优先策略：Douyidou 已返回 text 时直接使用（跳过ASR，零成本）
    if douyidou_result and douyidou_result.text:
        return await _save_text_result(
            db, user_id, persona_id, resolved.url, douyidou_result
        )

    # 无文案：走 ASR 转写（需要视频直链）
    video_url = douyidou_result.video_url if douyidou_result else None
    platform = douyidou_result.platform if douyidou_result else resolved.platform.value
    title = douyidou_result.title if douyidou_result else ""
    cover = douyidou_result.cover if douyidou_result else None

    if not video_url:
        # 降级链兜底
        parse_result, _ = await registry.run_with_fallback(
            "parse", registry.parse_chain, "parse_url", resolved.url
        )
        video_url = parse_result.video_key
        platform = parse_result.platform
        title = parse_result.title

    if not video_url:
        return ParseOut(transcript=None, degraded=True, platform=platform, title=title)

    # 探测视频时长（用于 ASR 分流决策：≤阈值走Flash同步，>阈值走异步）
    known_dur = douyidou_result.duration_sec if douyidou_result else None
    duration_sec = await probe_duration(video_url, platform=platform, known_duration=known_dur)
    logger.info(f"ASR 分流决策: duration={duration_sec}, threshold={300}s")

    # ASR 转写（直传视频URL，按时长智能分流）
    tr, provider_name = await registry.run_with_fallback(
        "asr", registry.asr_chain, "transcribe", video_url, duration_sec=duration_sec
    )
    transcript = TranscriptOut(
        text=tr.text, duration=tr.duration, language=tr.language,
        words=[WordTsOut(word=w.word, start=w.start, end=w.end) for w in tr.words],
    )
    script = await repo.create(
        db, user_id=user_id, persona_id=persona_id or "",
        title=title or "解析文案", source_url=resolved.url, platform=platform,
        original_text=tr.text,
        words_json=json.dumps([{"word": w.word, "start": w.start, "end": w.end} for w in tr.words],
                              ensure_ascii=False),
    )
    return ParseOut(
        transcript=transcript, degraded=False, platform=platform,
        title=title, scriptId=script.id, cover=cover,
        author=douyidou_result.author if douyidou_result else None,
    )


async def _save_text_result(
    db: AsyncSession, user_id: str, persona_id: str | None,
    source_url: str, result: DouyidouParseResult
) -> ParseOut:
    """Douyidou 已返回文案时直接落库（跳过ASR，零成本）"""
    text = result.text or ""
    script = await repo.create(
        db, user_id=user_id, persona_id=persona_id or "",
        title=result.title or text[:20], source_url=source_url,
        platform=result.platform, original_text=text, words_json="[]",
    )
    logger.info(f"文案优先命中，跳过ASR: platform={result.platform}, text_len={len(text)}")
    return ParseOut(
        transcript=TranscriptOut(text=text, words=[], duration=0, language="zh"),
        degraded=False, platform=result.platform,
        title=result.title, scriptId=script.id, cover=result.cover,
        author=result.author or None,
    )


async def parse_by_id(
    db: AsyncSession, user_id: str, video_id: str, platform: str, persona_id: str | None
) -> ParseOut:
    """通过视频ID + 平台解析（内部拼接URL后走统一链路）"""
    if platform == "douyin":
        url = f"https://www.douyin.com/video/{video_id}"
    elif platform == "xiaohongshu":
        url = f"https://www.xiaohongshu.com/explore/{video_id}"
    else:
        url = video_id  # 透传
    return await parse_url(db, user_id, url, persona_id)


async def parse_upload(db: AsyncSession, user_id: str, filename: str, data: bytes,
                       persona_id: str | None) -> ParseOut:
    """手动上传降级（视频号等平台，C2 兖底）"""
    key = await save_bytes("uploads", filename, data)
    # 按文件大小估算时长（用于 ASR 分流决策，短视频可走 Flash 同步）
    estimated_dur = len(data) / 300_000  # 默认码率 ~2.4Mbps
    tr, _ = await registry.run_with_fallback(
        "asr", registry.asr_chain, "transcribe", key, duration_sec=estimated_dur
    )
    script = await repo.create(
        db, user_id=user_id, persona_id=persona_id or "", title=filename, platform="upload",
        original_text=tr.text,
        words_json=json.dumps([{"word": w.word, "start": w.start, "end": w.end} for w in tr.words],
                              ensure_ascii=False),
    )
    return ParseOut(
        transcript=TranscriptOut(text=tr.text, duration=tr.duration, language=tr.language,
                                 words=[WordTsOut(word=w.word, start=w.start, end=w.end) for w in tr.words]),
        degraded=True, platform="upload", title=filename, scriptId=script.id,
    )


async def rewrite(db: AsyncSession, user_id: str, text: str, intensity: str,
                  prompt: str | None, script_id: str | None) -> dict:
    """三阶段IP仿写引擎：结构拆解 → IP化大纲 → 全文生成+校验闭环"""
    from .schemas import RewriteOut

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
        from app.modules.ipasset.service import get_active_persona_id
        from app.modules.ipasset.repository import get as get_persona
        from app.modules.ipasset.service import persona_prompt_context
        active_id = await get_active_persona_id(db, user_id)
        if active_id:
            persona = await get_persona(db, active_id, user_id)
            if persona:
                persona_ctx = persona_prompt_context(persona)

    llm = registry.get("llm")
    duration = persona.video_duration if persona else 60
    taboo_words = "、".join(json.loads(persona.taboo_words or "[]")) if persona else "无"
    cta_style = persona.cta_style if persona else "关注收藏"
    avoid_topics = json.loads(persona.avoid_topics or "[]") if persona else []

    # ---- Light 模式：单步人设润色 ----
    if intensity == "light":
        if persona_ctx:
            result = await llm.polish_light(text, persona_ctx)
        else:
            result, _ = await registry.run_with_fallback(
                "llm", registry.llm_chain, "rewrite", text, "light", prompt)
        # 禁忌词校验
        result, passed = _validate_taboo(result, taboo_words, avoid_topics)
        return RewriteOut(text=result, validationPassed=passed)

    # ---- Stage 1: 结构拆解 ----
    mode = "theme" if intensity == "theme" else "full"
    structure = await llm.analyze_structure(text, mode=mode)

    # ---- Stage 2: IP化大纲 ----
    outline = await llm.generate_outline(structure, persona_ctx, intensity, duration)

    # ---- Stage 3: 全文生成 ----
    constraints = {
        "duration": duration,
        "cta_style": cta_style or "关注收藏",
        "taboo_words": taboo_words,
    }
    result = await llm.generate_script(outline, persona_ctx, constraints)

    # ---- 校验闭环：禁忌词 + 去重检测（最多2轮再改写） ----
    validation_passed = True
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
        sim_result, _ = await registry.run_with_fallback(
            "llm", registry.llm_chain, "check_similarity", result)
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
        # 最终去重分
        sim_result, _ = await registry.run_with_fallback(
            "llm", registry.llm_chain, "check_similarity", result)
        validation_passed = sim_result.score <= 60

    # 落库
    if script_id:
        s = await repo.get(db, script_id, user_id)
        if s:
            s.rewritten_text = result
            await repo.save(db, s)

    # 最终去重分
    final_sim, _ = await registry.run_with_fallback(
        "llm", registry.llm_chain, "check_similarity", result)

    # 仿写完成：记录 INFO（§10.6.8-B #3）
    duration_ms = int((time.perf_counter() - start_time) * 1000)
    logger.info(
        "rewrite_done",
        user_id=user_id,
        intensity=intensity,
        duration_ms=duration_ms,
        text_len=len(result),
        similarity=final_sim.score,
    )

    return RewriteOut(
        text=result,
        structure=structure,
        outline=outline,
        similarity=final_sim.score,
        validationPassed=validation_passed,
    )


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


async def create_script(db: AsyncSession, user_id: str, persona_id: str | None,
                        title: str, text: str, platform: str, topic: str | None) -> ScriptOut:
    """手动创建文案资产（选题生成 / 直接编写入口），与解析产物同构"""
    script = await repo.create(
        db, user_id=user_id, persona_id=persona_id or "",
        title=title or (topic or text[:20] or "手动文案"),
        source_url="", platform=platform, original_text=text, words_json="[]",
    )
    return to_out(script)


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
        id=s.id, title=s.title, sourceUrl=s.source_url, platform=s.platform,
        originalText=s.original_text, rewrittenText=s.rewritten_text,
        similarityScore=s.similarity_score, status=s.status,
        createdAt=s.created_at.astimezone(UTC).isoformat(),
    )
