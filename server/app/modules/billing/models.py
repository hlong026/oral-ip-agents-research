"""billing 模块 ORM（06 文档 §8.6 / §11.2 扣费事务）"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def new_id() -> str:
    return uuid.uuid4().hex


class QuotaAccount(Base):
    """额度账户（点数制）"""

    __tablename__ = "quota_accounts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    balance: Mapped[float] = mapped_column(Float, default=0.0)
    total_granted: Mapped[float] = mapped_column(Float, default=0.0)
    used_this_month: Mapped[float] = mapped_column(Float, default=0.0)


class QuotaPrice(Base):
    """额度价格表：step × resolution × unit_price（§11.2）"""

    __tablename__ = "quota_price"
    __table_args__ = (UniqueConstraint("step", "resolution", name="uq_step_res"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    step: Mapped[str] = mapped_column(String(16))
    resolution: Mapped[str] = mapped_column(String(16), default="1080p")
    unit_price: Mapped[float] = mapped_column(Float)


class QuotaUsage(Base):
    """计量事件（trace_id 贯穿；本地通道免扣标注）"""

    __tablename__ = "quota_usage"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    task_id: Mapped[str] = mapped_column(String(32), index=True, default="")
    step: Mapped[str] = mapped_column(String(16))
    resolution: Mapped[str] = mapped_column(String(16), default="1080p")
    points: Mapped[float] = mapped_column(Float)  # 正=扣减，负=退还
    compute: Mapped[str] = mapped_column(String(8), default="cloud")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class PriceQuote(Base):
    """用户报价快照；任务执行始终引用该版本，不追随后来发布的新价格。"""

    __tablename__ = "price_quotes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    catalog_version_id: Mapped[str] = mapped_column(String(32), index=True)
    price_version: Mapped[str] = mapped_column(String(64))
    items_json: Mapped[str] = mapped_column(Text)
    estimated_points: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="quoted", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class CreditReservation(Base):
    """任务积分冻结；状态迁移只允许 reserved → settled/released。"""

    __tablename__ = "credit_reservations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    quote_id: Mapped[str] = mapped_column(String(64), index=True)
    task_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    reserved_points: Mapped[int] = mapped_column(Integer)
    actual_points: Mapped[int] = mapped_column(Integer, default=0)
    allocations_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(16), default="reserved", index=True)
    settled_by: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CreditGrant(Base):
    """套餐、充值和人工调整的积分批次，为后续按到期日消费保留来源。"""

    __tablename__ = "credit_grants"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    source_type: Mapped[str] = mapped_column(String(24), index=True)
    source_id: Mapped[str] = mapped_column(String(64), default="")
    granted_points: Mapped[int] = mapped_column(Integer)
    remaining_points: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CreditLedger(Base):
    """不可变积分流水；所有冻结、结算、释放和发放都追加记录。"""

    __tablename__ = "credit_ledger"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    event_type: Mapped[str] = mapped_column(String(24), index=True)
    points_delta: Mapped[int] = mapped_column(Integer)
    reference_type: Mapped[str] = mapped_column(String(24), default="")
    reference_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    price_version: Mapped[str] = mapped_column(String(64), default="")
    task_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_by: Mapped[str] = mapped_column(String(32), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


# 默认价格表（点数；运营定价毛利率 ≥60%）
DEFAULT_PRICES: list[tuple[str, str, float]] = [
    ("parse", "1080p", 1),
    ("asr", "1080p", 2),
    ("rewrite", "1080p", 2),
    ("voice", "1080p", 8),
    ("avatar", "1080p", 20),
    ("compose", "1080p", 3),
    ("edit", "1080p", 0),
    ("publish", "1080p", 1),
]
