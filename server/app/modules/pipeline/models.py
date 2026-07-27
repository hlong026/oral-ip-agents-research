"""pipeline 模块 ORM（06 文档 §10.2 流水线引擎）"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def new_id() -> str:
    return uuid.uuid4().hex


# STEP_ORDER（v1.1 回写：edit 为流水线第⑥步，自动模式可跳过）
STEP_ORDER = ["parse", "asr", "rewrite", "voice", "avatar", "compose", "edit", "publish"]

# UI 7 步映射: 链接/选题(parse+asr) → 文案(rewrite) → 声音(voice) → 数字人(avatar)
#              → 合成(compose) → 剪辑(edit) → 发布(publish)
UI_STEP_LABELS = {
    "parse": "链接/选题",
    "asr": "转写",
    "rewrite": "文案",
    "voice": "声音",
    "avatar": "数字人",
    "compose": "合成",
    "edit": "剪辑",
    "publish": "发布",
}


class PipelineTask(Base):
    """统一任务模型：steps JSON[8]，断点续跑，trace_id 贯穿"""

    __tablename__ = "pipeline_tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    ip_id: Mapped[str] = mapped_column(String(32), index=True, default="")
    title: Mapped[str] = mapped_column(String(128), default="未命名任务")
    source_url: Mapped[str] = mapped_column(String(512), default="")
    topic: Mapped[str] = mapped_column(String(256), default="")
    script_text: Mapped[str] = mapped_column(Text, default="")
    script_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    script_version: Mapped[int] = mapped_column(Integer, default=0)
    voice_id: Mapped[str] = mapped_column(String(64), default="")
    avatar_id: Mapped[str] = mapped_column(String(64), default="")
    platforms_json: Mapped[str] = mapped_column(String(128), default="[]")
    mode: Mapped[str] = mapped_column(String(8), default="auto")  # auto | manual（F-405）
    intensity: Mapped[str] = mapped_column(String(16), default="structure")  # light | structure | theme
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    # pending | running | waiting_confirm | reconciliation_required | done | failed | canceled
    current_step: Mapped[str] = mapped_column(String(16), default="")
    steps_json: Mapped[str] = mapped_column(Text, default="[]")  # StepState[8]
    artifacts_json: Mapped[str] = mapped_column(Text, default="{}")  # ctx.artifacts 持久化
    compute: Mapped[str] = mapped_column(String(8), default="cloud")  # MVP 恒 cloud
    quota_cost: Mapped[float] = mapped_column(Float, default=0.0)
    reservation_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    active_render_version: Mapped[int] = mapped_column(Integer, default=0)
    randomize: Mapped[bool] = mapped_column(Boolean, default=False)  # 差异化随机化（C5）
    batch_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    trace_id: Mapped[str] = mapped_column(String(64), default=new_id)
    error: Mapped[str] = mapped_column(Text, default="")
    queue_message_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    publish_at: Mapped[str] = mapped_column(String(32), default="")  # ISO 定时（F-503/F-722 预留）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class PipelineRenderVersion(Base):
    """一次独立重合成及其计费、配置和不可变产物。"""

    __tablename__ = "pipeline_render_versions"
    __table_args__ = (
        UniqueConstraint("task_id", "version", name="uq_pipeline_render_task_version"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_pipeline_render_user_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[int] = mapped_column(Integer)
    base_version: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    reservation_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    video_key: Mapped[str] = mapped_column(String(256), default="")
    cover_key: Mapped[str] = mapped_column(String(256), default="")
    quality_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    queue_message_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
