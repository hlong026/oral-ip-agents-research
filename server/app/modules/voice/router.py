"""voice HTTP 层：音色库 / 克隆 / 试听确认 / TTS（白标：不暴露供应商品牌）"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user_id
from app.core.storage import save_bytes
from app.modules.billing.service import (
    metered_operation,
    recover_reservation_after_failure,
    reserve_metered_operation,
)

from .schemas import CloneStatusOut, SynthesizeIn, SynthesizeOut, VoiceEditIn, VoiceOut
from .service import (
    clone_voice,
    confirm_voice,
    delete_voice,
    edit_voice_params,
    get_clone_status,
    list_voices,
    reject_voice,
    synthesize,
)

router = APIRouter(prefix="/voices", tags=["voice"])


@router.get("", response_model=list[VoiceOut])
async def api_list(user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    """我的声音列表"""
    return await list_voices(db, user_id)


@router.post("/clone", response_model=VoiceOut)
async def api_clone(
    name: str = Form(...),
    consentToken: str = Form(...),
    language: str = Form(default="zh"),
    quoteId: str | None = Form(None),
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """提交声音克隆（异步，返回 status=training）"""
    if len(consentToken.strip()) < 4:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "CONSENT_REQUIRED", "message": "声音克隆须本人授权（consent_token 缺失）"},
        )
    data = await file.read()
    reservation_id = await reserve_metered_operation(db, user_id, quoteId, "voice_clone", {"assets": 1})
    try:
        key = await save_bytes("voice-samples", file.filename or "sample.wav", data)
        return await clone_voice(db, user_id, name, consentToken, key, language, reservation_id)
    except BaseException:
        await recover_reservation_after_failure(db, reservation_id, user_id)
        raise


@router.get("/{voice_id}/status", response_model=CloneStatusOut)
async def api_clone_status(
    voice_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """查询克隆进度（完成后返回 demoUrl 试听链接）"""
    return await get_clone_status(db, user_id, voice_id)


@router.post("/{voice_id}/confirm", response_model=VoiceOut)
async def api_confirm(
    voice_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """用户试听确认通过"""
    return await confirm_voice(db, user_id, voice_id)


@router.post("/{voice_id}/reject", response_model=VoiceOut)
async def api_reject(
    voice_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """用户拒绝克隆结果"""
    return await reject_voice(db, user_id, voice_id)


@router.post("/{voice_id}/edit", status_code=204)
async def api_edit(
    voice_id: str,
    body: VoiceEditIn,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """调整语速/音量/语调"""
    await edit_voice_params(db, user_id, voice_id, body.rate, body.volume, body.pitch)
    return Response(status_code=204)


@router.delete("/{voice_id}", status_code=204)
async def api_delete(
    voice_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """删除声音"""
    await delete_voice(db, user_id, voice_id)
    return Response(status_code=204)


@router.post("/synthesize", response_model=SynthesizeOut)
async def api_synthesize(
    body: SynthesizeIn, user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)
):
    """TTS 合成试听"""
    characters = max(1, len(body.text))
    async with metered_operation(
        db,
        user_id,
        body.quoteId,
        "tts",
        {"characters": characters, "tokens": max(1, (characters + 1) // 2), "assets": 1},
    ):
        return await synthesize(db, user_id, body.voiceId, body.text, body.speed)
