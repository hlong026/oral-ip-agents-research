"""avatar HTTP 层：形象库 / 视频克隆 / 图片克隆 / 状态查询 / 删除（白标）"""

import math
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user_id
from app.core.storage import save_bytes
from app.modules.billing.service import (
    quote_operation_unit,
    recover_reservation_after_failure,
    reserve_metered_operation,
)
from app.providers.duration_probe import probe_media_bytes

from .schemas import AvatarOut, AvatarStatusOut
from .service import clone_avatar_by_image, clone_avatar_by_video, delete_avatar, get_clone_status, list_avatars

router = APIRouter(prefix="/avatars", tags=["avatar"])


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
    data = await file.read()
    unit = await quote_operation_unit(db, user_id, quoteId, "digital_human")
    duration = await probe_media_bytes(data, Path(file.filename or "").suffix)
    if unit in {"per_minute", "per_second"} and duration is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "MEDIA_DURATION_UNVERIFIED", "message": "无法验证训练视频时长"},
        )
    measures = {"seconds": max(1, math.ceil(duration or 1)), "assets": 1}
    reservation_id = await reserve_metered_operation(db, user_id, quoteId, "digital_human", measures)
    try:
        key = await save_bytes("avatar-samples", file.filename or "sample.mp4", data)
        cover_key = None
        if cover is not None and cover.filename:
            cover_key = await save_bytes("avatar-covers", cover.filename, await cover.read())
        return await clone_avatar_by_video(db, user_id, name, consentToken, key, scene, cover_key, reservation_id)
    except BaseException:
        await recover_reservation_after_failure(db, reservation_id, user_id)
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
    data = await file.read()
    reservation_id = await reserve_metered_operation(
        db,
        user_id,
        quoteId,
        "digital_human",
        {"seconds": 1, "images": 1, "assets": 1},
    )
    try:
        key = await save_bytes("avatar-samples", file.filename or "image.jpg", data)
        return await clone_avatar_by_image(db, user_id, name, consentToken, key, scene, reservation_id)
    except BaseException:
        await recover_reservation_after_failure(db, reservation_id, user_id)
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
