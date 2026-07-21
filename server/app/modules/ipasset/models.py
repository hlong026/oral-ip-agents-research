"""ipasset 模块 ORM（F-701 人设档案 / F-702 IP 资产库）"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def new_id() -> str:
    return uuid.uuid4().hex


class Persona(Base):
    """IP 档案：人设引擎字段全链路注入（领域/口吻/价值观/禁忌词/受众/风格样本）"""

    __tablename__ = "personas"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(64))
    domain: Mapped[str] = mapped_column(String(64), default="知识科普")
    tone: Mapped[str] = mapped_column(String(128), default="专业、接地气")
    values: Mapped[str] = mapped_column(Text, default="")
    taboo_words: Mapped[str] = mapped_column(Text, default="")  # JSON list
    avatar_char: Mapped[str] = mapped_column(String(4), default="口")
    avatar_grad: Mapped[str] = mapped_column(String(64), default="linear-gradient(135deg,#6366F1,#22D3EE)")
    voice_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # C8 资产绑定
    avatar_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # C8
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    # ---- 三阶段仿写引擎扩展字段 ----
    audience: Mapped[str] = mapped_column(Text, default="")  # 目标受众描述
    content_pillars: Mapped[str] = mapped_column(Text, default="[]")  # JSON list 内容支柱
    style_samples: Mapped[str] = mapped_column(Text, default="")  # 风格样本文本（few-shot）
    catchphrase: Mapped[str] = mapped_column(String(256), default="")  # 口头禅/标志性开场白
    video_duration: Mapped[int] = mapped_column(Integer, default=60)  # 偏好视频时长（秒）
    cta_style: Mapped[str] = mapped_column(String(128), default="")  # 行动号召风格
    avoid_topics: Mapped[str] = mapped_column(Text, default="[]")  # JSON list 回避话题
