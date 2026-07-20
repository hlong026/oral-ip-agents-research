"""
voice 业务编排（异步克隆 + 试听确认 + TTS 合成）
合规红线：克隆前强制本人授权校验（consent_token，§12.1）
白标：所有面向用户的响应不暴露供应商品牌
日志：声音克隆/TTS 合成（§10.6.8-B #4）
"""
import time
from datetime import UTC

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.storage import save_bytes
from app.providers.hifly import HiFlyAPIError, get_client
from app.providers.registry import registry

from . import repository as repo
from .models import Voice
from .schemas import CloneStatusOut, SynthesizeOut, VoiceOut, WordTsOut

logger = get_logger("oral.voice")


async def list_voices(db: AsyncSession, user_id: str) -> list[VoiceOut]:
    """我的声音列表（仅用户自己的，无公共/预置）"""
    items = await repo.list_by_user(db, user_id)
    return [to_out(v) for v in items]


async def clone_voice(db: AsyncSession, user_id: str, name: str, consent_token: str | None,
                      sample_key: str, language: str = "zh") -> VoiceOut:
    """
    声音克隆（异步）：
    1. consent_token 强制校验
    2. 调用 provider 提交克隆任务 → 获得 task_id
    3. 入库 status=training
    4. 前端通过 /voices/{id}/status 轮询 或等待 Webhook 回调
    """
    if not consent_token or len(consent_token.strip()) < 4:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail={"code": "CONSENT_REQUIRED", "message": "声音克隆须本人授权（consent_token 缺失）"})

    # 声音克隆提交：记录 INFO（§10.6.8-B #4）
    logger.info("voice_clone_start", user_id=user_id, voice_name=name)

    # 调用 provider 提交克隆（返回 task_id）
    try:
        task_id, provider_name = await registry.run_with_fallback(
            "voice", registry.voice_chain, "clone", name, sample_key, consent_token, language)
    except HiFlyAPIError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail={"code": "CLONE_FAILED", "message": e.user_message})

    v = await repo.create(db, user_id=user_id, name=name, source="clone", provider=provider_name,
                          provider_voice_id="", provider_task_id=task_id,
                          sample_key=sample_key, language=language, status="training")
    return to_out(v)


async def get_clone_status(db: AsyncSession, user_id: str, voice_id: str) -> CloneStatusOut:
    """
    查询克隆进度：
    - 如果 status 仍为 training，主动轮询一次 provider
    - 完成后下载 demo_url 转存，更新 status=pending_confirm
    """
    v = await repo.get(db, voice_id, user_id)
    if not v:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "声音不存在"})

    if v.status == "training" and v.provider_task_id:
        # 主动查询一次任务状态
        try:
            result, _ = await registry.run_with_fallback(
                "voice", registry.voice_chain, "query_clone_task", v.provider_task_id)
            task_status = result.get("status", 1)

            if task_status == 3:
                # 克隆完成：转存 demo 音频
                demo_url = result.get("demo_url", "")
                voice_id_remote = result.get("voice_id", "")
                demo_key = None
                if demo_url and demo_url.startswith("http"):
                    client = get_client()
                    demo_key = await client.download_to_storage(demo_url, "voice-demos", "demo.mp3")
                elif demo_url:
                    demo_key = demo_url  # mock 模式已经是本地路径

                v.provider_voice_id = voice_id_remote
                v.demo_key = demo_key
                v.status = "pending_confirm"
                await db.commit()
            elif task_status == 4:
                v.status = "failed"
                await db.commit()
        except Exception as e:
            logger.warning(f"voice clone status poll failed: {e}")

    return CloneStatusOut(
        id=v.id,
        status=v.status,
        demoUrl=f"/media/{v.demo_key}" if v.demo_key else None,
    )


async def confirm_voice(db: AsyncSession, user_id: str, voice_id: str) -> VoiceOut:
    """用户试听确认通过 → status=ready"""
    v = await repo.get(db, voice_id, user_id)
    if not v:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "声音不存在"})
    if v.status != "pending_confirm":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail={"code": "INVALID_STATUS", "message": "当前状态不可确认"})
    v.status = "ready"
    await db.commit()
    return to_out(v)


async def reject_voice(db: AsyncSession, user_id: str, voice_id: str) -> VoiceOut:
    """用户拒绝克隆结果 → status=rejected"""
    v = await repo.get(db, voice_id, user_id)
    if not v:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "声音不存在"})
    if v.status != "pending_confirm":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail={"code": "INVALID_STATUS", "message": "当前状态不可拒绝"})
    v.status = "rejected"
    await db.commit()
    return to_out(v)


async def edit_voice_params(db: AsyncSession, user_id: str, voice_id: str,
                            rate: str, volume: str, pitch: str) -> None:
    """修改声音参数（语速/音量/语调）"""
    v = await repo.get(db, voice_id, user_id)
    if not v:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "声音不存在"})
    if not v.provider_voice_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail={"code": "NOT_READY", "message": "声音尚未就绪"})

    try:
        client = get_client()
        await client.request("POST", "/api/v2/hifly/voice/edit", json={
            "voice": v.provider_voice_id,
            "rate": rate,
            "volume": volume,
            "pitch": pitch,
        })
    except HiFlyAPIError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail={"code": "EDIT_FAILED", "message": e.user_message})

    v.rate = rate
    v.volume = volume
    v.pitch = pitch
    await db.commit()


async def synthesize(db: AsyncSession, user_id: str, voice_id: str, text: str, speed: float) -> SynthesizeOut:
    """TTS 合成试听"""
    v = await repo.get(db, voice_id, user_id)
    if not v:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "声音不存在"})
    if v.status != "ready":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail={"code": "NOT_READY", "message": "声音尚未就绪，请先完成克隆确认"})
    provider_voice_id = v.provider_voice_id or voice_id

    start_time = time.perf_counter()
    result, _ = await registry.run_with_fallback(
        "voice", registry.voice_chain, "synthesize", provider_voice_id, text, speed)
    # TTS 合成完成：记录 INFO（§10.6.8-B #4）
    duration_ms = int((time.perf_counter() - start_time) * 1000)
    logger.info(
        "tts_done",
        user_id=user_id,
        voice_id=voice_id,
        duration_ms=duration_ms,
        audio_duration_sec=result.duration,
    )
    return SynthesizeOut(
        audioUrl=f"/media/{result.audio_key}",
        words=[WordTsOut(word=w.word, start=w.start, end=w.end) for w in result.words],
    )


async def handle_voice_callback(db: AsyncSession, task_id: str, status_code: int,
                                voice_id_remote: str, demo_url: str) -> None:
    """Webhook 回调处理（type=3 声音克隆完成）"""
    from sqlalchemy import select

    stmt = select(Voice).where(Voice.provider_task_id == task_id)
    result = await db.execute(stmt)
    v = result.scalar_one_or_none()
    if not v:
        logger.warning(f"voice callback: no record for task_id={task_id}")
        return

    if v.status != "training":
        return  # 幂等：已处理过

    if status_code == 3:
        # 下载 demo_url 转存
        demo_key = None
        if demo_url and demo_url.startswith("http"):
            client = get_client()
            demo_key = await client.download_to_storage(demo_url, "voice-demos", "demo.mp3")
        v.provider_voice_id = voice_id_remote
        v.demo_key = demo_key
        v.status = "pending_confirm"
    else:
        v.status = "failed"
    await db.commit()


def to_out(v: Voice) -> VoiceOut:
    return VoiceOut(
        id=v.id, name=v.name, source=v.source, gender=v.gender,
        emotion=v.emotion, language=v.language,
        sampleUrl=f"/media/{v.sample_key}" if v.sample_key else None,
        demoUrl=f"/media/{v.demo_key}" if v.demo_key else None,
        rate=v.rate, volume=v.volume, pitch=v.pitch,
        status=v.status, createdAt=v.created_at.astimezone(UTC).isoformat(),
    )
