"""首次部署管理员引导；只读取服务端环境变量，不开放注册接口。"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.security import hash_password
from app.modules.auth import repository as auth_repo
from app.modules.auth.models import User

logger = get_logger("oral.bootstrap")


async def ensure_bootstrap_admin(db: AsyncSession, settings: Settings) -> None:
    phone = settings.bootstrap_admin_phone.strip()
    password = settings.bootstrap_admin_password
    if not phone and not password:
        return
    if not phone or len(password) < 12:
        raise RuntimeError("BOOTSTRAP_ADMIN_PHONE 与至少 12 位的 BOOTSTRAP_ADMIN_PASSWORD 必须同时配置")
    existing = await auth_repo.get_by_phone(db, phone)
    if existing:
        if existing.role != "admin":
            raise RuntimeError("引导管理员手机号已属于普通用户，拒绝自动提权")
        return
    db.add(
        User(
            phone=phone,
            password_hash=hash_password(password),
            nickname="系统管理员",
            avatar_char="管",
            role="admin",
        )
    )
    await db.commit()
    logger.warning("bootstrap_admin_created", phone_suffix=phone[-4:])
