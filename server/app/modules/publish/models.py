"""publish 模块 ORM（F-501~F-504：扫码授权、发布任务、失败降级）"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

PLATFORMS = ["douyin", "xiaohongshu", "shipinhao"]
PLATFORM_NAMES = {"douyin": "抖音", "xiaohongshu": "小红书", "shipinhao": "视频号"}


def new_id() -> str:
    return uuid.uuid4().hex


class PublishAccount(Base):
    """平台账号：扫码授权后的浏览器会话以 Fernet 密文落库。"""

    __tablename__ = "publish_accounts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    platform: Mapped[str] = mapped_column(String(16), index=True)
    nickname: Mapped[str] = mapped_column(String(64), default="")
    session_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | expired
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class PublishJob(Base):
    """发布任务：queued → publishing → success | failed（可重试/仅导出 MP4 降级）"""

    __tablename__ = "publish_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    task_id: Mapped[str] = mapped_column(String(32), index=True, default="")
    account_id: Mapped[str] = mapped_column(String(32), default="")
    platform: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(128), default="")
    topics_json: Mapped[str] = mapped_column(String(256), default="[]")
    video_key: Mapped[str] = mapped_column(String(256), default="")
    cover_key: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    # queued | publishing | success | failed
    scheduled_at: Mapped[str] = mapped_column(String(32), default="")  # ISO 定时发布（F-503）
    error: Mapped[str] = mapped_column(Text, default="")
    post_id: Mapped[str] = mapped_column(String(64), default="")
    # post_id 来源：internal=内部追踪号（SAU 发布无法拿到平台作品 ID，哈希生成）| platform=平台真实作品 ID（回捞回填）
    post_id_source: Mapped[str] = mapped_column(String(16), default="")
    retry_count: Mapped[str] = mapped_column(String(8), default="0")
    queue_message_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    export_key: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
