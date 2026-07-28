"""设备绑定核心逻辑（硬件机器码多设备绑定，docs/19）

指纹格式 {设备段}.{特征哈希}：
- 桌面端设备段为 hw-{机器码哈希}（清缓存/重装不变）
- 网页端设备段为 localStorage UUID（软指纹兜底）
匹配规则沿用 fingerprint_matches 哲学：设备段严格一致，特征哈希容忍漂移。
"""

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.db import SessionLocal
from app.core.dynamic_config import get_config_int
from app.core.logging import get_logger

from .models import DeviceBindRequest, UserDevice, device_key_of

logger = get_logger("oral.auth.devices")

DEFAULT_DEVICE_BIND_LIMIT = 1


async def get_device_bind_limit() -> int:
    """每账号可绑定设备数（后台 device_bind_limit 配置，默认 1，钳制 1~10）"""
    limit = await get_config_int("device_bind_limit", DEFAULT_DEVICE_BIND_LIMIT)
    return min(max(limit, 1), 10)


def describe_device(fingerprint: str) -> tuple[str, str, str]:
    """按设备段前缀推导 (device_key, source, device_name)"""
    key = device_key_of(fingerprint)
    if key.startswith("hw-"):
        return key, "desktop-hw", "桌面端设备"
    return key, "web", "网页端设备"


async def list_user_devices(db: AsyncSession, user_id: str) -> list[UserDevice]:
    rows = await db.execute(
        select(UserDevice).where(UserDevice.user_id == user_id).order_by(UserDevice.created_at.asc())
    )
    return list(rows.scalars().all())


async def bind_first_device(db: AsyncSession, user_id: str, fingerprint: str) -> None:
    """首次激活开户：直接写入第一条设备记录（不 commit，随开户事务提交）"""
    if not fingerprint:
        return
    key, source, name = describe_device(fingerprint)
    db.add(
        UserDevice(
            user_id=user_id,
            fingerprint=fingerprint,
            device_key=key[:64],
            device_name=name,
            source=source,
        )
    )


async def _upsert_pending_request(user_id: str, fingerprint: str) -> None:
    """独立会话落库申请（登录事务随 403 被回滚，申请必须先持久化）；幂等。"""
    key, _, name = describe_device(fingerprint)
    async with SessionLocal() as session:
        existing = (
            await session.execute(
                select(DeviceBindRequest).where(
                    DeviceBindRequest.user_id == user_id,
                    DeviceBindRequest.device_key == key[:64],
                    DeviceBindRequest.status == "pending",
                )
            )
        ).scalar_one_or_none()
        if existing:
            # 重复登录：仅刷新指纹（特征哈希可能漂移），不产生新申请
            existing.fingerprint = fingerprint
            await session.commit()
            return
        session.add(
            DeviceBindRequest(
                user_id=user_id,
                fingerprint=fingerprint,
                device_key=key[:64],
                device_name=name,
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            # 并发登录撞部分唯一索引：已有 pending 申请，幂等忽略
            await session.rollback()


async def ensure_device_allowed(db: AsyncSession, user_id: str, fingerprint: str) -> None:
    """登录设备校验状态机（不 commit，随登录事务提交）：

    - 设备段在列表 → 通过（特征哈希漂移则更新指纹）
    - 不在列表且数量 < 上限 → 自动绑定（审计 device_auto_bound）
    - 不在列表且数量 ≥ 上限 → 独立会话落库 pending 申请 + 403 DEVICE_LIMIT_REACHED
    """
    if not fingerprint:
        return
    key, source, name = describe_device(fingerprint)
    devices = await list_user_devices(db, user_id)
    now = datetime.now(UTC)
    matched = next((d for d in devices if d.device_key == key[:64]), None)
    if matched:
        if matched.fingerprint != fingerprint:
            logger.warning("fingerprint_drift", user_id=user_id, source="device_check")
            matched.fingerprint = fingerprint
        matched.last_seen_at = now
        return
    limit = await get_device_bind_limit()
    if len(devices) < limit:
        try:
            # savepoint + flush：同设备并发登录撞唯一索引时幂等放行，不向用户暴露 500
            async with db.begin_nested():
                db.add(
                    UserDevice(
                        user_id=user_id,
                        fingerprint=fingerprint,
                        device_key=key[:64],
                        device_name=name,
                        source=source,
                    )
                )
                await db.flush()
        except IntegrityError:
            logger.info("device_bind_race_ignored", user_id=user_id, device_key=key[:8])
            return
        logger.info("device_auto_bound", user_id=user_id, device_key=key[:8], source=source)
        await write_audit("device_auto_bound", user_id=user_id, detail=f"device={key[:8]},source={source}")
        return
    await _upsert_pending_request(user_id, fingerprint)
    logger.warning("device_limit_reached", user_id=user_id, device_key=key[:8], bound=len(devices), limit=limit)
    await write_audit("device_limit_reached", user_id=user_id, detail=f"device={key[:8]},bound={len(devices)}")
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        detail={
            "code": "DEVICE_LIMIT_REACHED",
            "message": f"该激活码已绑定 {len(devices)} 台设备达到上限，已提交新设备申请，请联系管理员审批",
        },
    )


async def device_matches_bound(db: AsyncSession, user_id: str, fingerprint: str) -> bool:
    """refresh 场景：设备段是否在绑定列表中（无任何绑定记录时视为未绑定，放行）。
    命中时同步更新漂移指纹与最近活跃时间（随调用方事务提交）。"""
    devices = await list_user_devices(db, user_id)
    if not devices:
        return True
    key = device_key_of(fingerprint)[:64]
    matched = next((d for d in devices if d.device_key == key), None)
    if matched is None:
        return False
    if fingerprint and matched.fingerprint != fingerprint:
        logger.warning("fingerprint_drift", user_id=user_id, source="refresh")
        matched.fingerprint = fingerprint
    matched.last_seen_at = datetime.now(UTC)
    return True
