"""content HTTP 层：解析 / 仿写 / 去重 / 选题 / 文案资产"""

import math
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_active_persona_id, get_current_user_id
from app.modules.billing.service import metered_operation, quote_operation_unit
from app.providers.duration_probe import probe_media_bytes

from .schemas import (
    ParseIn,
    ParseOut,
    ProbeUrlIn,
    ProbeUrlOut,
    RewriteIn,
    RewriteOut,
    ScriptCreateIn,
    ScriptOut,
    SimilarityIn,
    SimilarityOut,
    TopicsIn,
    TopicsOut,
)
from .service import (
    create_script,
    get_script,
    list_scripts,
    parse_by_id,
    parse_upload,
    parse_url,
    probe_url_duration,
    rewrite,
    similarity,
    topics,
)

router = APIRouter(prefix="/content", tags=["content"])


@router.post("/probe", response_model=ProbeUrlOut)
async def api_probe_url(
    body: ProbeUrlIn,
    _user_id: str = Depends(get_current_user_id),
) -> ProbeUrlOut:
    duration = await probe_url_duration(body.url, required=True)
    return ProbeUrlOut(durationSeconds=duration or 0)


@router.post("/parse", response_model=ParseOut)
async def api_parse(
    body: str | None = Form(None),
    url: str | None = Form(None),
    quoteId: str | None = Form(None),
    file: UploadFile | None = File(None),
    user_id: str = Depends(get_current_user_id),
    persona_id: str | None = Depends(get_current_active_persona_id),
    db: AsyncSession = Depends(get_db),
):
    if file is not None:
        data = await file.read()
        unit = await quote_operation_unit(db, user_id, quoteId, "asr")
        duration = await probe_media_bytes(data, Path(file.filename or "").suffix)
        if unit in {"per_minute", "per_second"} and duration is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "MEDIA_DURATION_UNVERIFIED", "message": "无法验证媒体时长，暂不能执行转写"},
            )
        seconds = max(1, math.ceil(duration or 1))
        async with metered_operation(
            db,
            user_id,
            quoteId,
            "asr",
            {"seconds": seconds, "assets": 1},
        ):
            return await parse_upload(
                db,
                user_id,
                file.filename or "upload.mp4",
                data,
                persona_id,
                duration,
            )
    target = url or body
    if not target:
        # JSON 形式兼容
        return ParseOut(transcript=None, degraded=True, platform=None, title=None)
    unit = await quote_operation_unit(db, user_id, quoteId, "asr")
    time_priced = unit in {"per_minute", "per_second"}
    duration = await probe_url_duration(target, required=True) if time_priced else None
    seconds = max(1, math.ceil(duration or 1))
    async with metered_operation(db, user_id, quoteId, "asr", {"seconds": seconds, "assets": 1}):
        return await parse_url(db, user_id, target, persona_id, duration)


@router.post("/parse/json", response_model=ParseOut)
async def api_parse_json(
    body: ParseIn,
    user_id: str = Depends(get_current_user_id),
    persona_id: str | None = Depends(get_current_active_persona_id),
    db: AsyncSession = Depends(get_db),
):
    # 支持两种输入：url 或 videoId + platform
    unit = await quote_operation_unit(db, user_id, body.quoteId, "asr")
    time_priced = unit in {"per_minute", "per_second"}
    if body.videoId and body.platform:
        if body.platform == "douyin":
            target = f"https://www.douyin.com/video/{body.videoId}"
        elif body.platform == "xiaohongshu":
            target = f"https://www.xiaohongshu.com/explore/{body.videoId}"
        else:
            target = body.videoId
    else:
        target = body.url or ""
    duration = await probe_url_duration(target, required=True) if time_priced else None
    seconds = max(1, math.ceil(duration or 1))
    async with metered_operation(db, user_id, body.quoteId, "asr", {"seconds": seconds, "assets": 1}):
        if body.videoId and body.platform:
            return await parse_by_id(db, user_id, body.videoId, body.platform, persona_id, duration)
        return await parse_url(db, user_id, target, persona_id, duration)


@router.post("/rewrite", response_model=RewriteOut)
async def api_rewrite(body: RewriteIn, user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    billable_text = body.text + (body.prompt or "")
    characters = max(1, len(billable_text))
    async with metered_operation(
        db,
        user_id,
        body.quoteId,
        "script_generation",
        {"characters": characters, "tokens": max(1, (characters + 1) // 2), "assets": 1},
    ):
        return await rewrite(db, user_id, body.text, body.intensity, body.prompt, body.scriptId)


@router.post("/similarity", response_model=SimilarityOut)
async def api_similarity(
    body: SimilarityIn,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    characters = max(1, len(body.text))
    async with metered_operation(
        db,
        user_id,
        body.quoteId,
        "script_generation",
        {"characters": characters, "tokens": max(1, (characters + 1) // 2), "assets": 1},
    ):
        return await similarity(body.text)


@router.post("/topics", response_model=TopicsOut)
async def api_topics(
    body: TopicsIn,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    characters = max(1, len(body.keyword))
    async with metered_operation(
        db,
        user_id,
        body.quoteId,
        "topic_generation",
        {"characters": characters, "tokens": max(1, (characters + 1) // 2), "assets": 1},
    ):
        return TopicsOut(topics=await topics(body.keyword))


@router.post("/scripts", response_model=ScriptOut)
async def api_create_script(
    body: ScriptCreateIn,
    user_id: str = Depends(get_current_user_id),
    persona_id: str | None = Depends(get_current_active_persona_id),
    db: AsyncSession = Depends(get_db),
):
    return await create_script(db, user_id, persona_id, body.title, body.text, body.platform, body.topic)


@router.get("/scripts", response_model=list[ScriptOut])
async def api_scripts(user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await list_scripts(db, user_id)


@router.get("/scripts/{script_id}", response_model=ScriptOut)
async def api_script(script_id: str, user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await get_script(db, user_id, script_id)
