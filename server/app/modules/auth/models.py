"""auth 模块 ORM"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def new_id() -> str:
    return uuid.uuid4().hex


def device_key_of(fingerprint: str) -> str:
    """提取指纹设备段（"." 前的 UUID / hw- 机器码段）"""
    return fingerprint.partition(".")[0]


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
    # 设备绑定指纹（已废弃：迁入 user_devices 多设备表，本字段停止读写，下期清理）
    device_fingerprint: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class UserDevice(Base):
    """用户已绑定设备列表（硬件机器码 / 浏览器软指纹，每账号上限由 device_bind_limit 配置）"""

    __tablename__ = "user_devices"
    __table_args__ = (Index("uq_user_devices_user_key", "user_id", "device_key", unique=True),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    # 完整指纹（含特征哈希段，漂移时更新）
    fingerprint: Mapped[str] = mapped_column(String(128))
    # 设备段冗余列（指纹按 "." 切分首段），唯一索引建在 (user_id, device_key)
    device_key: Mapped[str] = mapped_column(String(64))
    device_name: Mapped[str] = mapped_column(String(64), default="")
    # "desktop-hw" | "web"（按设备段是否 hw- 前缀判定）
    source: Mapped[str] = mapped_column(String(16), default="web")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class DeviceBindRequest(Base):
    """超限新设备绑定申请（pending 由管理员审批解绑旧设备后放行）"""

    __tablename__ = "device_bind_requests"
    # 同一新设备只保留一条待审申请（部分唯一索引）
    __table_args__ = (
        Index(
            "uq_device_bind_requests_pending",
            "user_id",
            "device_key",
            unique=True,
            sqlite_where=text("status = 'pending'"),
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    fingerprint: Mapped[str] = mapped_column(String(128))
    device_key: Mapped[str] = mapped_column(String(64))
    device_name: Mapped[str] = mapped_column(String(64), default="")
    # "pending" | "approved" | "rejected"
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str] = mapped_column(String(32), default="")


class RefreshSession(Base):
    """刷新令牌会话（设备绑定 + 单端互踢可配置，C7）"""

    __tablename__ = "refresh_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True, default="web")
    refresh_jti: Mapped[str] = mapped_column(String(64), unique=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
