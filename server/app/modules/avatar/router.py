"""avatar HTTP 层：形象库 / 视频克隆 / 图片克隆 / 状态查询 / 删除（白标）"""

import math
import warnings
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user_id
from app.core.storage import UploadTooLarge, delete, read_limited, save_bytes, save_stream
from app.modules.billing.service import (
    quote_operation_unit,
    recover_reservation_after_failure,
    reserve_metered_operation,
)
from app.providers.duration_probe import probe_media_key

from .schemas import AvatarOut, AvatarStatusOut
from .service import clone_avatar_by_image, clone_avatar_by_video, delete_avatar, get_clone_status, list_avatars

router = APIRouter(prefix="/avatars", tags=["avatar"])

# 飞影数字人训练素材硬约束：mp4/mov（h264），≤500MB，官方 5s～30min；产品侧收紧为 30s～3min
AVATAR_VIDEO_FORMATS = {"mp4", "mov"}
AVATAR_VIDEO_MAX_BYTES = 500 * 1024 * 1024
AVATAR_VIDEO_MIN_SECONDS = 30
AVATAR_VIDEO_MAX_SECONDS = 180
AVATAR_IMAGE_MAX_BYTES = 10 * 1024 * 1024
AVATAR_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
AVATAR_IMAGE_MAX_DIMENSION = 8192


async def _read_valid_image(file: UploadFile) -> bytes:
    try:
        data = await read_limited(file, AVATAR_IMAGE_MAX_BYTES)
    except UploadTooLarge as exc:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            detail={"code": "IMAGE_TOO_LARGE", "message": "图片不能超过 10MB"},
        ) from exc
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                image.verify()
            with Image.open(BytesIO(data)) as image:
                image_format = image.format
                width, height = image.size
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, UnidentifiedImageError, OSError) as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "INVALID_IMAGE", "message": "图片格式无效"},
        ) from exc
    if (
        image_format not in AVATAR_IMAGE_FORMATS
        or width <= 0
        or height <= 0
        or max(width, height) > AVATAR_IMAGE_MAX_DIMENSION
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "INVALID_IMAGE", "message": "仅支持尺寸不超过 8192px 的 JPEG、PNG、WEBP 图片"},
        )
    return data


@router.get("", response_model=list[AvatarOut])
async def api_list(user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    """我的数字人列表"""
    return await list_avatars(db, user_id)


@router.post("/clone", response_model=AvatarOut)
async def api_clone_video(
    name: str = Form(...),
    consentToken: str = Form(...),
    scene: str = Form(default=""),
    quoteId: str | None = Form(None),
    file: UploadFile = File(...),
    cover: UploadFile | None = File(default=None),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """视频数字人克隆（异步，返回 status=training）"""
    if len(consentToken.strip()) < 4:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "CONSENT_REQUIRED", "message": "形象克隆须本人授权（consent_token 缺失）"},
        )
    suffix = Path(file.filename or "").suffix.lower()
    if suffix.lstrip(".") not in AVATAR_VIDEO_FORMATS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "VIDEO_FORMAT_UNSUPPORTED", "message": "训练视频仅支持 MP4/MOV（H264 编码）"},
        )
    key = ""
    cover_key = None
    reservation_id = ""
    try:
        key, _ = await save_stream(
            "avatar-samples",
            file.filename or "sample.mp4",
            file,
            max_bytes=AVATAR_VIDEO_MAX_BYTES,
        )
        info = await probe_media_key(key)
        streams = (info or {}).get("streams")
        video_stream = next(
            (stream for stream in streams or [] if isinstance(stream, dict) and stream.get("codec_type") == "video"),
            None,
        )
        if video_stream is None or video_stream.get("codec_name") != "h264":
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "INVALID_VIDEO", "message": "训练视频必须是可识别的 H264 视频"},
            )
        try:
            duration = float((info or {})["format"]["duration"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "MEDIA_DURATION_UNVERIFIED", "message": "无法验证训练视频时长"},
            ) from exc
        if not (AVATAR_VIDEO_MIN_SECONDS <= duration <= AVATAR_VIDEO_MAX_SECONDS):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "VIDEO_DURATION_INVALID", "message": "训练视频时长需在 30 秒～3 分钟之间"},
            )
        await quote_operation_unit(db, user_id, quoteId, "digital_human")
        measures = {"seconds": max(1, math.ceil(duration)), "assets": 1}
        reservation_id = await reserve_metered_operation(db, user_id, quoteId, "digital_human", measures)
        if cover is not None and cover.filename:
            cover_key = await save_bytes("avatar-covers", cover.filename, await _read_valid_image(cover))
        return await clone_avatar_by_video(db, user_id, name, consentToken, key, scene, cover_key, reservation_id)
    except UploadTooLarge as exc:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            detail={"code": "VIDEO_TOO_LARGE", "message": "训练视频超过 500MB，请压缩后重试"},
        ) from exc
    except BaseException:
        if reservation_id:
            await recover_reservation_after_failure(db, reservation_id, user_id)
        if key:
            await delete(key)
        if cover_key:
            await delete(cover_key)
        raise


@router.post("/create-by-image", response_model=AvatarOut)
async def api_clone_image(
    name: str = Form(...),
    consentToken: str = Form(...),
    scene: str = Form(default=""),
    quoteId: str | None = Form(None),
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """图片数字人克隆（异步，返回 status=training）"""
    if len(consentToken.strip()) < 4:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "CONSENT_REQUIRED", "message": "形象克隆须本人授权（consent_token 缺失）"},
        )
    data = await _read_valid_image(file)
    reservation_id = await reserve_metered_operation(
        db,
        user_id,
        quoteId,
        "digital_human",
        {"seconds": 1, "images": 1, "assets": 1},
    )
    key = ""
    try:
        key = await save_bytes("avatar-samples", file.filename or "image.jpg", data)
        return await clone_avatar_by_image(db, user_id, name, consentToken, key, scene, reservation_id)
    except BaseException:
        await recover_reservation_after_failure(db, reservation_id, user_id)
        if key:
            await delete(key)
        raise


@router.get("/{avatar_id}/status", response_model=AvatarStatusOut)
async def api_clone_status(
    avatar_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """查询克隆进度"""
    return await get_clone_status(db, user_id, avatar_id)


@router.delete("/{avatar_id}", status_code=204)
async def api_delete(
    avatar_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """删除数字人"""
    await delete_avatar(db, user_id, avatar_id)
    return Response(status_code=204)
