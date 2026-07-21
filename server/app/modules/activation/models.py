"""activation 模块 ORM（激活码 + 批次 + 订阅记录）"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def new_id() -> str:
    return uuid.uuid4().hex


class ActivationCode(Base):
    """激活码（一码一户，服务端验证）"""

    __tablename__ = "activation_codes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    plan_type: Mapped[str] = mapped_column(String(16), default="monthly")
    quota_amount: Mapped[float] = mapped_column(Float, default=0.0)
    duration_days: Mapped[int] = mapped_column(Integer, default=30)
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
    quota_granted: Mapped[float] = mapped_column(Float, default=0.0)
    duration_days: Mapped[int] = mapped_column(Integer, default=0)
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
