"""content 模块 ORM（文案资产沉淀）"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def new_id() -> str:
    return uuid.uuid4().hex


class Script(Base):
    """文案（转写/仿写产物，文案工坊数据源）"""

    __tablename__ = "scripts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    persona_id: Mapped[str] = mapped_column(String(32), index=True, default="")
    title: Mapped[str] = mapped_column(String(128), default="未命名文案")
    source_url: Mapped[str] = mapped_column(String(512), default="")
    platform: Mapped[str] = mapped_column(String(16), default="")
    original_text: Mapped[str] = mapped_column(Text, default="")
    rewritten_text: Mapped[str] = mapped_column(Text, default="")
    words_json: Mapped[str] = mapped_column(Text, default="[]")  # 字级时间戳
    similarity_score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | confirmed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
