"""content HTTP 层：解析 / 仿写 / 去重 / 选题 / 文案资产"""

import math
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_active_persona_id, get_current_user_id
from app.core.storage import UploadTooLarge, delete, save_stream
from app.modules.billing.service import metered_operation, quote_operation_unit
from app.providers.duration_probe import probe_media_key

from . import jobs
from .schemas import (
    BatchRewriteIn,
    BatchRewriteOut,
    ContentJobOut,
    ParseIn,
    ParseOut,
    ProbeUrlIn,
    ProbeUrlOut,
    RewriteIn,
    RewriteOut,
    ScriptCreateIn,
    ScriptOut,
    ScriptUpdateIn,
    ScriptVersionOut,
    SimilarityIn,
    SimilarityOut,
    TopicsIn,
    TopicsOut,
)
from .service import (
    batch_rewrite,
    create_script,
    get_script,
    list_script_versions,
    list_scripts,
    parse_by_id,
    parse_text,
    parse_upload,
    parse_url,
    probe_url_duration,
    rewrite,
    similarity,
    topics,
    update_script,
)

router = APIRouter(prefix="/content", tags=["content"])

_ALLOWED_UPLOAD_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".mp3", ".wav", ".m4a"}
_MAX_UPLOAD_BYTES = 500 * 1024 * 1024


def _validate_upload(filename: str, data: bytes) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED_UPLOAD_SUFFIXES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "UNSUPPORTED_FORMAT",
                "message": "仅支持 MP4、MOV、AVI、MKV、MP3、WAV、M4A 文件",
            },
        )
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            detail={
                "code": "FILE_TOO_LARGE",
                "message": f"上传文件不能超过 {_MAX_UPLOAD_BYTES // (1024 * 1024)}MB",
            },
        )


def _validate_upload_filename(filename: str) -> None:
    _validate_upload(filename, b"")


def _verified_duration(info: dict | None) -> float:
    streams = (info or {}).get("streams")
    if not isinstance(streams, list) or not any(
        stream.get("codec_type") in {"audio", "video"} for stream in streams if isinstance(stream, dict)
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "INVALID_MEDIA", "message": "上传文件不是可识别的音视频"},
        )
    try:
        duration = float((info or {})["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "MEDIA_DURATION_UNVERIFIED", "message": "无法验证媒体时长"},
        ) from exc
    if duration <= 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "MEDIA_DURATION_UNVERIFIED", "message": "无法验证媒体时长"},
        )
    return duration


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
        filename = file.filename or ""
        _validate_upload_filename(filename)
        storage_key = ""
        try:
            storage_key, _ = await save_stream("uploads", filename, file, max_bytes=_MAX_UPLOAD_BYTES)
            duration = _verified_duration(await probe_media_key(storage_key))
            await quote_operation_unit(db, user_id, quoteId, "asr")
            seconds = max(1, math.ceil(duration))
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
                    filename,
                    None,
                    persona_id,
                    duration,
                    storage_key=storage_key,
                )
        except UploadTooLarge as exc:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                detail={
                    "code": "FILE_TOO_LARGE",
                    "message": f"上传文件不能超过 {_MAX_UPLOAD_BYTES // (1024 * 1024)}MB",
                },
            ) from exc
        except BaseException:
            if storage_key:
                await delete(storage_key)
            raise
    if body:
        return await parse_text(db, user_id, body, persona_id)
    target = url
    if not target:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "INPUT_REQUIRED", "message": "请提供链接、正文或上传文件"},
        )
    unit = await quote_operation_unit(db, user_id, quoteId, "asr")
    time_priced = unit in {"per_minute", "per_second"}
    url_duration = await probe_url_duration(target, required=True) if time_priced else None
    seconds = max(1, math.ceil(url_duration or 1))
    async with metered_operation(db, user_id, quoteId, "asr", {"seconds": seconds, "assets": 1}):
        return await parse_url(db, user_id, target, persona_id, url_duration)


@router.post(
    "/jobs/parse",
    response_model=ContentJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def api_submit_parse_job(
    url: str | None = Form(None),
    quoteId: str | None = Form(None),
    file: UploadFile | None = File(None),
    user_id: str = Depends(get_current_user_id),
    persona_id: str | None = Depends(get_current_active_persona_id),
    db: AsyncSession = Depends(get_db),
) -> ContentJobOut:
    if file is not None:
        filename = file.filename or ""
        _validate_upload_filename(filename)
        storage_key = ""
        try:
            storage_key, _ = await save_stream("content-jobs", filename, file, max_bytes=_MAX_UPLOAD_BYTES)
            duration = _verified_duration(await probe_media_key(storage_key))
            return await jobs.submit_parse_upload(
                db,
                user_id=user_id,
                persona_id=persona_id,
                filename=filename,
                data=None,
                quote_id=quoteId,
                storage_key=storage_key,
                duration_seconds=duration,
            )
        except UploadTooLarge as exc:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                detail={
                    "code": "FILE_TOO_LARGE",
                    "message": f"上传文件不能超过 {_MAX_UPLOAD_BYTES // (1024 * 1024)}MB",
                },
            ) from exc
        except BaseException:
            if storage_key:
                await delete(storage_key)
            raise
    if not url:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "INPUT_REQUIRED", "message": "请提供链接或上传文件"},
        )
    return await jobs.submit_parse_url(
        db,
        user_id=user_id,
        persona_id=persona_id,
        url=url,
        quote_id=quoteId,
    )


@router.post("/parse/json", response_model=ParseOut)
async def api_parse_json(
    body: ParseIn,
    user_id: str = Depends(get_current_user_id),
    persona_id: str | None = Depends(get_current_active_persona_id),
    db: AsyncSession = Depends(get_db),
):
    if body.body:
        return await parse_text(db, user_id, body.body, persona_id)
    if not (body.url or body.videoId):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "INPUT_REQUIRED", "message": "请提供链接、正文或视频 ID"},
        )
    # 支持链接或 videoId + platform
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


@router.post(
    "/jobs/rewrite",
    response_model=ContentJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def api_submit_rewrite_job(
    body: RewriteIn,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> ContentJobOut:
    return await jobs.submit_rewrite(
        db,
        user_id=user_id,
        text=body.text,
        intensity=body.intensity,
        prompt=body.prompt,
        script_id=body.scriptId,
        quote_id=body.quoteId,
    )


@router.post("/rewrite/batch", response_model=BatchRewriteOut)
async def api_batch_rewrite(
    body: BatchRewriteIn,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    characters = max(1, len(body.text) * body.count)
    async with metered_operation(
        db,
        user_id,
        body.quoteId,
        "script_generation",
        {"characters": characters, "tokens": max(1, (characters + 1) // 2), "assets": body.count},
    ):
        return await batch_rewrite(
            db,
            user_id,
            body.text,
            body.intensity,
            body.count,
            body.prompt,
            body.scriptId,
        )


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


@router.post(
    "/jobs/similarity",
    response_model=ContentJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def api_submit_similarity_job(
    body: SimilarityIn,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> ContentJobOut:
    return await jobs.submit_similarity(
        db,
        user_id=user_id,
        text=body.text,
        quote_id=body.quoteId,
    )


@router.get("/jobs/{job_id}", response_model=ContentJobOut)
async def api_content_job(
    job_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> ContentJobOut:
    return await jobs.get_job(db, user_id, job_id)


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


@router.put("/scripts/{script_id}", response_model=ScriptOut)
async def api_update_script(
    script_id: str,
    body: ScriptUpdateIn,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await update_script(db, user_id, script_id, title=body.title, text=body.text)


@router.get("/scripts/{script_id}/versions", response_model=list[ScriptVersionOut])
async def api_script_versions(
    script_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await list_script_versions(db, user_id, script_id)
