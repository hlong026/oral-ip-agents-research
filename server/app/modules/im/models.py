"""im 模块 ORM（抖音私信自动回复：会话、消息、规则、监听状态）"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def new_id() -> str:
    return uuid.uuid4().hex


class IMConversation(Base):
    """私信会话（一个绑定账号与一个远端用户的对话）"""

    __tablename__ = "im_conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(String(32), index=True)  # FK → publish_accounts.id
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    platform: Mapped[str] = mapped_column(String(16), default="douyin")
    remote_uid: Mapped[str] = mapped_column(String(64), default="")
    remote_nickname: Mapped[str] = mapped_column(String(64), default="")
    remote_avatar: Mapped[str] = mapped_column(String(256), default="")
    dy_conversation_id: Mapped[str] = mapped_column(String(64), default="")
    dy_conversation_short_id: Mapped[str] = mapped_column(String(64), default="")
    dy_ticket: Mapped[str] = mapped_column(String(128), default="")
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    unread_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | archived
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class IMMessage(Base):
    """私信消息记录"""

    __tablename__ = "im_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "remote_message_id", name="uq_im_messages_remote_message"),
        UniqueConstraint(
            "conversation_id",
            "direction",
            "remote_index",
            name="uq_im_messages_remote_index",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    direction: Mapped[str] = mapped_column(String(4), default="in")  # in | out
    msg_type: Mapped[int] = mapped_column(Integer, default=7)  # 7=文本 5=表情 17=语音 27=图片 8=视频
    content: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    auto_replied: Mapped[bool] = mapped_column(Boolean, default=False)
    rule_id: Mapped[str] = mapped_column(String(32), default="", index=True)  # 触发的规则 ID
    reply_content: Mapped[str] = mapped_column(Text, default="")
    remote_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    remote_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    send_status: Mapped[str] = mapped_column(String(16), default="received", index=True)
    send_error: Mapped[str] = mapped_column(String(256), default="")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    manual_takeover: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class IMAutoReplyRule(Base):
    """自动回复规则"""

    __tablename__ = "im_auto_reply_rules"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    account_id: Mapped[str] = mapped_column(String(32), default="")  # 空=全局
    name: Mapped[str] = mapped_column(String(64), default="")
    trigger_type: Mapped[str] = mapped_column(String(16), default="all")  # keyword | all | llm
    trigger_pattern: Mapped[str] = mapped_column(String(256), default="")
    reply_mode: Mapped[str] = mapped_column(String(16), default="template")  # template | llm
    reply_template: Mapped[str] = mapped_column(Text, default="")
    llm_prompt: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[int] = mapped_column(Integer, default=100)
    daily_limit: Mapped[int] = mapped_column(Integer, default=50)
    delay_min: Mapped[int] = mapped_column(Integer, default=3)
    delay_max: Mapped[int] = mapped_column(Integer, default=30)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class IMListenerState(Base):
    """IM 监听状态（每个绑定账号一条）"""

    __tablename__ = "im_listener_states"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default="disconnected")
    # listening | disconnected | error
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_msg: Mapped[str] = mapped_column(String(256), default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
