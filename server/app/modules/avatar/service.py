"""avatar 业务编排（仅用户自有形象，视频/图片克隆，多场景，白标不暴露供应商）
日志：数字人克隆（§10.6.8-B #4）
"""

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import consent_fingerprint
from app.core.white_label import public_error_message
from app.providers.hifly import HiFlyAPIError
from app.providers.registry import registry

from . import repository as repo
from .models import Avatar
from .schemas import AvatarOut, AvatarStatusOut

logger = get_logger("oral.avatar")


async def list_avatars(db: AsyncSession, user_id: str) -> list[AvatarOut]:
    """我的数字人列表（仅用户自己的，无公共/预置形象）"""
    items = await repo.list_by_user(db, user_id)
    return [to_out(a) for a in items]


async def clone_avatar_by_video(
    db: AsyncSession,
    user_id: str,
    name: str,
    consent_token: str | None,
    video_key: str,
    scene: str = "",
    cover_key: str | None = None,
    reservation_id: str = "",
) -> AvatarOut:
    """
    视频数字人克隆（异步）：
    1. consent_token 强制校验
    2. 调用 provider 提交克隆任务 → 获得 task_id
    3. 入库 status=training
    """
    if not consent_token or len(consent_token.strip()) < 4:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "CONSENT_REQUIRED", "message": "形象克隆须本人授权（consent_token 缺失）"},
        )

    # 数字人克隆提交：记录 INFO（§10.6.8-B #4）
    logger.info("avatar_clone_start", user_id=user_id, avatar_name=name, clone_type="video")

    try:
        task_id, provider_name = await registry.run_with_fallback(
            "avatar", registry.avatar_chain, "clone_by_video", name, video_key, consent_token
        )
    except HiFlyAPIError as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "CLONE_FAILED", "message": public_error_message(e)},
        ) from e

    a = await repo.create(
        db,
        user_id=user_id,
        name=name,
        source="clone",
        provider=provider_name,
        provider_avatar_id="",
        provider_task_id=task_id,
        reservation_id=reservation_id,
        avatar_type="video",
        scene=scene,
        cover_key=cover_key,
        preview_key=video_key,
        consent_hash=consent_fingerprint(user_id, "avatar", consent_token),
        consented_at=datetime.now(UTC),
        status="training",
    )
    return to_out(a)


async def clone_avatar_by_image(
    db: AsyncSession,
    user_id: str,
    name: str,
    consent_token: str | None,
    image_key: str,
    scene: str = "",
    reservation_id: str = "",
) -> AvatarOut:
    """
    图片数字人克隆（异步）：
    1. consent_token 强制校验
    2. 调用 provider 提交克隆任务 → 获得 task_id
    3. 入库 status=training
    """
    if not consent_token or len(consent_token.strip()) < 4:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "CONSENT_REQUIRED", "message": "形象克隆须本人授权（consent_token 缺失）"},
        )

    # 数字人克隆提交：记录 INFO（§10.6.8-B #4）
    logger.info("avatar_clone_start", user_id=user_id, avatar_name=name, clone_type="image")

    try:
        task_id, provider_name = await registry.run_with_fallback(
            "avatar", registry.avatar_chain, "clone_by_image", name, image_key, 2
        )
    except HiFlyAPIError as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "CLONE_FAILED", "message": public_error_message(e)},
        ) from e

    a = await repo.create(
        db,
        user_id=user_id,
        name=name,
        source="clone",
        provider=provider_name,
        provider_avatar_id="",
        provider_task_id=task_id,
        reservation_id=reservation_id,
        avatar_type="image",
        scene=scene,
        cover_key=image_key,
        preview_key=image_key,
        consent_hash=consent_fingerprint(user_id, "avatar", consent_token),
        consented_at=datetime.now(UTC),
        status="training",
    )
    return to_out(a)


async def _finalize_clone_billing(db: AsyncSession, avatar: Avatar, succeeded: bool) -> None:
    if not avatar.reservation_id:
        await db.commit()
        return
    from app.modules.billing.service import release_reservation, settle_reservation

    if succeeded:
        settled = await settle_reservation(
            db,
            avatar.reservation_id,
            avatar.id,
            step="digital_human",
        )
        if settled <= 0:
            raise RuntimeError("avatar clone billing settlement failed")
    else:
        released = await release_reservation(db, avatar.reservation_id, avatar.user_id)
        if released is None or released.status != "released":
            raise RuntimeError("avatar clone billing reservation missing")


async def _transition_clone(
    db: AsyncSession,
    avatar: Avatar,
    *,
    succeeded: bool,
    provider_avatar_id: str = "",
) -> bool:
    """Atomically claim the provider result before billing it."""
    values = {
        "status": "ready" if succeeded else "failed",
        "provider_avatar_id": provider_avatar_id if succeeded else avatar.provider_avatar_id,
    }
    result = await db.execute(
        update(Avatar).where(Avatar.id == avatar.id, Avatar.status == "training").values(**values)
    )
    if int(getattr(result, "rowcount", 0) or 0) != 1:
        await db.rollback()
        await db.refresh(avatar)
        return False
    try:
        await _finalize_clone_billing(db, avatar, succeeded)
    except Exception:
        await db.rollback()
        await db.refresh(avatar)
        raise
    await db.refresh(avatar)
    return True


async def get_clone_status(db: AsyncSession, user_id: str, avatar_id: str) -> AvatarStatusOut:
    """
    查询克隆进度：
    - 如果 status 仍为 training，主动轮询一次 provider
    - 完成后更新 provider_avatar_id + status=ready
    """
    a = await repo.get(db, avatar_id, user_id)
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "数字人不存在"})

    progress = 0
    if a.status == "training" and a.provider_task_id:
        try:
            result, _ = await registry.run_with_fallback(
                "avatar", registry.avatar_chain, "query_avatar_task", a.provider_task_id
            )
            task_status = result.get("status", 1)

            if task_status == 1:
                progress = 10
            elif task_status == 2:
                progress = 50
            elif task_status == 3:
                provider_avatar_id = result.get("avatar_id", "")
                progress = 100
                transitioned = await _transition_clone(db, a, succeeded=True, provider_avatar_id=provider_avatar_id)
                if transitioned:
                    logger.info(
                        "avatar_clone_done", user_id=user_id, avatar_id=a.id, provider_avatar_id=a.provider_avatar_id
                    )
            elif task_status == 4:
                progress = 100
                await _transition_clone(db, a, succeeded=False)
        except Exception as e:
            await db.rollback()
            await db.refresh(a)
            logger.warning(f"avatar clone status poll failed: {e}")
    elif a.status == "ready":
        progress = 100

    return AvatarStatusOut(id=a.id, status=a.status, progress=progress)


async def delete_avatar(db: AsyncSession, user_id: str, avatar_id: str) -> None:
    """删除数字人"""
    a = await repo.get(db, avatar_id, user_id)
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "数字人不存在"})
    if a.status == "training" and a.reservation_id:
        from app.modules.billing.service import release_reservation

        await release_reservation(db, a.reservation_id, user_id)
    await repo.delete(db, a)


async def resolve_provider_avatar_id(db: AsyncSession, user_id: str, avatar_id: str) -> str:
    """解析用户 avatar_id → provider_avatar_id（pipeline 内部使用）"""
    a = await repo.get(db, avatar_id, user_id)
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "数字人不存在"})
    if a.status != "ready":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail={"code": "NOT_READY", "message": "数字人尚未就绪"})
    return a.provider_avatar_id or avatar_id


async def handle_avatar_callback(db: AsyncSession, task_id: str, status_code: int, avatar_id_remote: str) -> None:
    """Webhook 回调处理（type=2 数字人克隆完成）"""
    from sqlalchemy import select

    stmt = select(Avatar).where(Avatar.provider_task_id == task_id)
    result = await db.execute(stmt)
    a = result.scalar_one_or_none()
    if not a:
        logger.warning(f"avatar callback: no record for task_id={task_id}")
        return

    if a.status != "training":
        return  # 幂等

    if status_code == 3:
        transitioned = await _transition_clone(db, a, succeeded=True, provider_avatar_id=avatar_id_remote)
        if transitioned:
            logger.info("avatar_clone_done", user_id=a.user_id, avatar_id=a.id, provider_avatar_id=avatar_id_remote)
    else:
        await _transition_clone(db, a, succeeded=False)


def to_out(a: Avatar) -> AvatarOut:
    return AvatarOut(
        id=a.id,
        name=a.name,
        source=a.source,
        avatarType=a.avatar_type,
        scene=a.scene,
        style=a.style,
        coverUrl=f"/media/{a.cover_key}" if a.cover_key else None,
        previewUrl=f"/media/{a.preview_key}" if a.preview_key else None,
        status=a.status,
        createdAt=a.created_at.astimezone(UTC).isoformat(),
    )
