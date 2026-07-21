"""avatar 模块 ORM（F-301~F-304，仅用户自有形象，支持视频/图片克隆 + 多场景）"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def new_id() -> str:
    return uuid.uuid4().hex


class Avatar(Base):
    __tablename__ = "avatars"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16), default="clone")  # clone（无 public）
    provider: Mapped[str] = mapped_column(String(32), default="")  # 内部用，不暴露给用户
    provider_avatar_id: Mapped[str] = mapped_column(String(64), default="")
    provider_task_id: Mapped[str] = mapped_column(String(64), default="")  # 克隆任务 ID
    reservation_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    avatar_type: Mapped[str] = mapped_column(String(16), default="video")  # video | image
    scene: Mapped[str] = mapped_column(String(32), default="")  # 场景标签（商务/生活/知识/电商等）
    style: Mapped[str] = mapped_column(String(32), default="")
    cover_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    preview_key: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 预览视频/图片
    # status: training → ready / failed
    status: Mapped[str] = mapped_column(String(20), default="training")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
