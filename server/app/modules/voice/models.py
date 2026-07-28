"""voice 模块 ORM（F-201~F-204，异步克隆 + 试听确认流程）"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def new_id() -> str:
    return uuid.uuid4().hex


class Voice(Base):
    __tablename__ = "voices"
    __table_args__ = (
        Index(
            "uq_voices_provider_task_id",
            "provider_task_id",
            unique=True,
            sqlite_where=text("provider_task_id <> ''"),
            postgresql_where=text("provider_task_id <> ''"),
        ),
        # 数据完整性兜底：同一供应商声音 ID 全库唯一，防重复认领
        Index(
            "uq_voices_provider_voice_id",
            "provider_voice_id",
            unique=True,
            sqlite_where=text("provider_voice_id <> ''"),
            postgresql_where=text("provider_voice_id <> ''"),
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16), default="clone")  # clone
    provider: Mapped[str] = mapped_column(String(32), default="")  # 内部用，不暴露给用户
    provider_voice_id: Mapped[str] = mapped_column(String(64), default="")
    provider_task_id: Mapped[str] = mapped_column(String(64), default="")  # 异步克隆任务 ID
    reservation_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    gender: Mapped[str] = mapped_column(String(16), default="")
    emotion: Mapped[str] = mapped_column(String(32), default="")
    language: Mapped[str] = mapped_column(String(16), default="zh")  # zh/en/jp/ko 等
    sample_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    demo_key: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 试听音频存储 key
    consent_hash: Mapped[str] = mapped_column(String(64), default="")
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rate: Mapped[str] = mapped_column(String(8), default="1.0")  # 语速
    volume: Mapped[str] = mapped_column(String(8), default="1.0")  # 音量
    pitch: Mapped[str] = mapped_column(String(8), default="1.0")  # 语调
    # status: training → pending_confirm → ready / rejected / failed
    status: Mapped[str] = mapped_column(String(32), default="training")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
