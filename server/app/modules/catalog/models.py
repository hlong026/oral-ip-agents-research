"""套餐 SKU、价格目录 ORM。"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def new_id() -> str:
    return uuid.uuid4().hex


class PlanSku(Base):
    """稳定 SKU 主记录；经济字段保存在不可变版本中。"""

    __tablename__ = "plan_skus"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class PlanSkuVersion(Base):
    """可售套餐版本。发布后不修改经济字段，改价通过克隆新版本完成。"""

    __tablename__ = "plan_sku_versions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    sku_id: Mapped[str] = mapped_column(String(32), index=True)
    code: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    name: Mapped[str] = mapped_column(String(64))
    subtitle: Mapped[str] = mapped_column(String(128), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    badge: Mapped[str] = mapped_column(String(32), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    sku_type: Mapped[str] = mapped_column(String(32), default="annual_bundle")
    audience: Mapped[str] = mapped_column(String(16), default="public", index=True)
    duration_days: Mapped[int] = mapped_column(Integer, default=365)
    monthly_points: Mapped[int] = mapped_column(Integer, default=0)
    one_time_points: Mapped[int] = mapped_column(Integer, default=0)
    list_price_cents: Mapped[int] = mapped_column(Integer, default=0)
    display_price_cents: Mapped[int] = mapped_column(Integer, default=0)
    entitlements_json: Mapped[str] = mapped_column(Text, default="[]")
    max_concurrency: Mapped[int] = mapped_column(Integer, default=1)
    max_resolution: Mapped[str] = mapped_column(String(16), default="1080p")
    purchase_instructions: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PriceCatalogVersion(Base):
    """模块积分价格版本。"""

    __tablename__ = "price_catalog_versions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    version: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    created_by: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModulePrice(Base):
    """一个模块在某个价格版本中的积分单价。"""

    __tablename__ = "module_prices"
    __table_args__ = (UniqueConstraint("catalog_version_id", "module", name="uq_catalog_module"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    catalog_version_id: Mapped[str] = mapped_column(String(32), index=True)
    module: Mapped[str] = mapped_column(String(32), index=True)
    display_name: Mapped[str] = mapped_column(String(64))
    billing_unit: Mapped[str] = mapped_column(String(32))
    unit_size: Mapped[int] = mapped_column(Integer, default=1)
    points_per_unit: Mapped[int] = mapped_column(Integer, default=0)
    minimum_points: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    public_description: Mapped[str] = mapped_column(Text, default="")
    internal_cost_cents_per_unit: Mapped[int] = mapped_column(Integer, default=0)
    target_margin_bps: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
