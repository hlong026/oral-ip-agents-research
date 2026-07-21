"""settings 模块 ORM（Provider 配置持久化，前端设置页写入）"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ProviderConfig(Base):
    """Provider 配置键值对（全局单租户，设置页统一管理）"""

    __tablename__ = "provider_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
