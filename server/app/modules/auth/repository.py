"""auth 数据访问层"""
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import RefreshSession, User


async def get_by_phone(db: AsyncSession, phone: str) -> User | None:
    res = await db.execute(select(User).where(User.phone == phone))
    return res.scalar_one_or_none()


async def get_by_id(db: AsyncSession, user_id: str) -> User | None:
    res = await db.execute(select(User).where(User.id == user_id))
    return res.scalar_one_or_none()


async def create_user(db: AsyncSession, phone: str, password_hash: str, nickname: str) -> User:
    user = User(phone=phone, password_hash=password_hash, nickname=nickname or phone[-4:],
                avatar_char=(nickname or phone)[0])
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def save_session(db: AsyncSession, user_id: str, device_id: str, jti: str) -> None:
    db.add(RefreshSession(user_id=user_id, device_id=device_id, refresh_jti=jti))
    await db.commit()


async def is_jti_valid(db: AsyncSession, jti: str) -> bool:
    res = await db.execute(select(RefreshSession.revoked).where(RefreshSession.refresh_jti == jti))
    row = res.scalar_one_or_none()
    return row is False


async def revoke_device_sessions(db: AsyncSession, user_id: str, device_id: str) -> None:
    """单端互踢：同设备旧会话全部吊销（C7 可配置）"""
    await db.execute(
        update(RefreshSession)
        .where(RefreshSession.user_id == user_id, RefreshSession.device_id == device_id)
        .values(revoked=True)
    )
    await db.commit()
