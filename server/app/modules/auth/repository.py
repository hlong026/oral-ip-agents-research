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


async def get_by_id_for_update(db: AsyncSession, user_id: str) -> User | None:
    """串行化同一用户的任务创建；PostgreSQL 在事务结束前持有行锁。"""
    res = await db.execute(select(User).where(User.id == user_id).with_for_update())
    return res.scalar_one_or_none()


async def create_user(db: AsyncSession, phone: str, password_hash: str, nickname: str) -> User:
    user = User(
        phone=phone, password_hash=password_hash, nickname=nickname or phone[-4:], avatar_char=(nickname or phone)[0]
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update_password(db: AsyncSession, user_id: str, new_password_hash: str) -> None:
    """更新用户密码哈希"""
    await db.execute(update(User).where(User.id == user_id).values(password_hash=new_password_hash))
    await db.commit()


async def update_password_and_revoke_sessions(db: AsyncSession, user_id: str, new_password_hash: str) -> None:
    """同一事务内更新密码并吊销所有刷新会话（消除安全窗口）"""
    await db.execute(update(User).where(User.id == user_id).values(password_hash=new_password_hash))
    await db.execute(
        update(RefreshSession).where(RefreshSession.user_id == user_id, RefreshSession.revoked.is_(False)).values(revoked=True)
    )
    await db.commit()


async def update_phone(db: AsyncSession, user_id: str, new_phone: str) -> None:
    """换绑手机号"""
    await db.execute(update(User).where(User.id == user_id).values(phone=new_phone))
    await db.commit()


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


async def revoke_all_sessions(db: AsyncSession, user_id: str) -> None:
    """吊销用户所有刷新会话（修改密码后强制重新登录）"""
    await db.execute(
        update(RefreshSession).where(RefreshSession.user_id == user_id, RefreshSession.revoked.is_(False)).values(revoked=True)
    )
    await db.commit()


async def rotate_refresh_session(db: AsyncSession, old_jti: str, user_id: str, device_id: str, new_jti: str) -> None:
    """刷新令牌轮换：同一事务吊销旧 JTI 并保存新 JTI，防重放。"""
    await db.execute(
        update(RefreshSession)
        .where(
            RefreshSession.refresh_jti == old_jti,
            RefreshSession.user_id == user_id,
            RefreshSession.revoked.is_(False),
        )
        .values(revoked=True)
    )
    db.add(RefreshSession(user_id=user_id, device_id=device_id, refresh_jti=new_jti))
    await db.commit()
