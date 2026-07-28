"""voice HTTP 层：音色库 / 克隆 / 试听确认 / TTS（白标：不暴露供应商品牌）"""

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user_id
from app.core.storage import UploadTooLarge, read_limited, save_bytes
from app.modules.billing.service import (
    metered_operation,
    recover_reservation_after_failure,
    reserve_metered_operation,
)
from app.providers.duration_probe import (
    MediaProcessingError,
    probe_media_bytes_info,
    transcode_audio_to_m4a,
)

from .schemas import CloneStatusOut, CloudImportIn, CloudVoiceOut, SynthesizeIn, SynthesizeOut, VoiceEditIn, VoiceOut
from .service import (
    clone_voice,
    confirm_voice,
    delete_voice,
    edit_voice_params,
    get_clone_status,
    import_cloud_voice,
    list_cloud_voices,
    list_voices,
    reject_voice,
    synthesize,
)

router = APIRouter(prefix="/voices", tags=["voice"])

# 飞影声音克隆素材硬约束：mp3/m4a/wav，≤20MB，5秒～3分钟
VOICE_SAMPLE_FORMATS = {"mp3", "m4a", "wav"}
VOICE_SAMPLE_MAX_BYTES = 20 * 1024 * 1024
VOICE_SAMPLE_MIN_SECONDS = 5
VOICE_SAMPLE_MAX_SECONDS = 180


@router.get("", response_model=list[VoiceOut])
async def api_list(user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    """我的声音列表"""
    return await list_voices(db, user_id)


@router.get("/cloud", response_model=list[CloudVoiceOut])
async def api_cloud_list(user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    """云端历史克隆声音找回列表（已与本地库去重比对）"""
    return await list_cloud_voices(db, user_id)


@router.post("/cloud/import", response_model=VoiceOut)
async def api_cloud_import(
    body: CloudImportIn,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """一键导入云端历史声音（免重新克隆，不消耗算力）"""
    return await import_cloud_voice(db, user_id, body.cloudId, body.name, body.consentToken)


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
    try:
        data = await read_limited(file, VOICE_SAMPLE_MAX_BYTES)
    except UploadTooLarge as exc:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            detail={"code": "AUDIO_TOO_LARGE", "message": "声音样本超过 20MB，请压缩或剪短后重试"},
        ) from exc
    suffix = Path(file.filename or "").suffix.lower()
    filename = file.filename or "sample.wav"
    # 浏览器录音（webm/ogg 等）不在供应商支持列表内，先转码为 m4a 再入库
    if suffix.lstrip(".") not in VOICE_SAMPLE_FORMATS:
        try:
            data = await transcode_audio_to_m4a(data, suffix)
        except MediaProcessingError as e:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "AUDIO_FORMAT_UNSUPPORTED", "message": f"音频格式不支持且转码失败：{e}"},
            ) from e
        suffix = ".m4a"
        filename = f"{Path(filename).stem}.m4a"
    if len(data) > VOICE_SAMPLE_MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            detail={"code": "AUDIO_TOO_LARGE", "message": "声音样本超过 20MB，请压缩或剪短后重试"},
        )
    info = await probe_media_bytes_info(data, suffix)
    streams = (info or {}).get("streams")
    if not isinstance(streams, list) or not any(
        stream.get("codec_type") == "audio" for stream in streams if isinstance(stream, dict)
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "INVALID_AUDIO", "message": "声音样本不是可识别的音频"},
        )
    try:
        duration = float((info or {})["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "AUDIO_DURATION_INVALID", "message": "无法验证声音样本时长"},
        ) from exc
    if not (VOICE_SAMPLE_MIN_SECONDS <= duration <= VOICE_SAMPLE_MAX_SECONDS):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "AUDIO_DURATION_INVALID", "message": "声音样本时长需在 5 秒～3 分钟之间"},
        )
    reservation_id = await reserve_metered_operation(db, user_id, quoteId, "voice_clone", {"assets": 1})
    try:
        key = await save_bytes("voice-samples", filename, data)
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


@router.delete("/{voice_id}", status_code=204)
async def api_delete(
    voice_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """删除声音（训练中释放预留积分，自动解绑 IP）"""
    await delete_voice(db, user_id, voice_id)
    return Response(status_code=204)


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
