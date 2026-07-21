"""activation 模块 ORM（激活码 + 批次 + 订阅记录）"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def new_id() -> str:
    return uuid.uuid4().hex


class ActivationCode(Base):
    """激活码（一码一户，服务端验证）"""

    __tablename__ = "activation_codes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # 字段名为兼容既有表保留；新数据只保存 64 位 HMAC 摘要，不保存明文激活码。
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    plan_type: Mapped[str] = mapped_column(String(16), default="monthly")
    quota_amount: Mapped[float] = mapped_column(Float, default=0.0)
    duration_days: Mapped[int] = mapped_column(Integer, default=30)
    sku_version_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    plan_sku_code: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16), default="unused", index=True)
    batch_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    channel: Mapped[str] = mapped_column(String(32), default="")
    bound_user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class ActivationBatch(Base):
    """激活码批次（渠道溯源 + 批量管理）"""

    __tablename__ = "activation_batches"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(64), default="")
    plan_type: Mapped[str] = mapped_column(String(16), default="monthly")
    quota_amount: Mapped[float] = mapped_column(Float, default=0.0)
    duration_days: Mapped[int] = mapped_column(Integer, default=30)
    sku_version_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    plan_sku_code: Mapped[str] = mapped_column(String(64), default="")
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    channel: Mapped[str] = mapped_column(String(32), default="")
    code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    created_by: Mapped[str] = mapped_column(String(32), default="")


class UserSubscription(Base):
    """用户订阅/续费记录"""

    __tablename__ = "user_subscriptions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    code_id: Mapped[str] = mapped_column(String(32))
    plan_type: Mapped[str] = mapped_column(String(16))
    sku_version_id: Mapped[str] = mapped_column(String(32), default="")
    plan_sku_code: Mapped[str] = mapped_column(String(64), default="")
    quota_granted: Mapped[float] = mapped_column(Float, default=0.0)
    duration_days: Mapped[int] = mapped_column(Integer, default=0)
    monthly_points: Mapped[int] = mapped_column(Integer, default=0)
    grants_issued: Mapped[int] = mapped_column(Integer, default=0)
    next_grant_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class ActivationRateLimit(Base):
    """Persistent failed-attempt counter keyed by a protected identity digest."""

    __tablename__ = "activation_rate_limits"
    __table_args__ = (UniqueConstraint("scope", "subject_hash", "action", name="uq_activation_rate_subject"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    scope: Mapped[str] = mapped_column(String(16))
    subject_hash: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(16))
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
