"""auth 模块 ORM"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def new_id() -> str:
    return uuid.uuid4().hex


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # 手机号/密码仅管理员使用；激活码用户为 NULL
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, index=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    nickname: Mapped[str] = mapped_column(String(64), default="")
    avatar_char: Mapped[str] = mapped_column(String(4), default="口")
    role: Mapped[str] = mapped_column(String(16), default="user", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # 激活码扩展字段
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plan_type: Mapped[str] = mapped_column(String(16), default="none")
    plan_sku_code: Mapped[str] = mapped_column(String(64), default="")
    plan_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 设备绑定指纹（空 = 未绑定，登录时自动绑定）
    device_fingerprint: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class RefreshSession(Base):
    """刷新令牌会话（设备绑定 + 单端互踢可配置，C7）"""

    __tablename__ = "refresh_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True, default="web")
    refresh_jti: Mapped[str] = mapped_column(String(64), unique=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
