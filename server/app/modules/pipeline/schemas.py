"""pipeline 出入参"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CreatePipelineIn(BaseModel):
    ipId: str
    sourceUrl: str | None = None
    topic: str | None = None
    scriptText: str | None = None
    scriptId: str | None = None
    scriptVersion: int | None = Field(default=None, ge=1)
    voiceId: str | None = None
    avatarId: str | None = None
    mode: str = "auto"
    intensity: str = "structure"  # light | structure | theme
    platforms: list[str] = []
    publishAt: str | None = None
    randomize: bool = False
    count: int = 1  # 批量（F-406，≥20 队列）
    quoteId: str | None = None


class StepStateOut(BaseModel):
    step: str
    status: str
    progress: float
    message: str = ""
    compute: str = "cloud"
    provider: str = ""
    quotaCost: float = 0.0
    artifacts: dict[str, str] = {}
    startedAt: str | None = None
    finishedAt: str | None = None
    durationMs: int | None = None


class RetryStepIn(BaseModel):
    quoteId: str | None = None


class SubtitleStyleIn(BaseModel):
    fontSize: int = Field(default=44, ge=32, le=64)
    color: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    position: Literal["bottom", "middle", "top"] = "bottom"
    stroke: int = Field(default=2, ge=0, le=6)


class EditConfigIn(BaseModel):
    subtitleStyle: SubtitleStyleIn = Field(default_factory=SubtitleStyleIn)
    # 素材库尚未开放真实归属校验前，只允许关闭 BGM，避免伪曲库或任意 storage key。
    bgmMode: Literal["off"] = "off"
    bgmVolume: int = Field(default=0, ge=0, le=100)
    coverTemplate: Literal["bold-bottom", "center-band", "top-title", "none"] = "bold-bottom"

    @model_validator(mode="after")
    def validate_bgm(self) -> "EditConfigIn":
        if self.bgmMode == "off" and self.bgmVolume != 0:
            raise ValueError("BGM 关闭时音量必须为 0")
        return self


class RecomposeIn(BaseModel):
    quoteId: str
    idempotencyKey: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")
    baseVersion: int = Field(ge=1)
    config: EditConfigIn


class RenderVersionOut(BaseModel):
    id: str
    taskId: str
    version: int
    baseVersion: int
    status: str
    config: EditConfigIn
    videoUrl: str | None = None
    coverUrl: str | None = None
    quality: dict[str, object] = {}
    error: str = ""
    isActive: bool
    createdAt: str
    updatedAt: str


class TaskOut(BaseModel):
    id: str
    ipId: str
    scriptId: str = ""
    scriptVersion: int = 0
    title: str
    coverUrl: str | None = None
    sourceUrl: str
    mode: str
    status: str
    steps: list[StepStateOut]
    currentStep: str | None = None
    compute: str
    quotaCost: float
    error: str = ""
    artifacts: dict[str, object] = {}
    activeRenderVersion: int = 0
    batchId: str | None = None
    createdAt: str
    updatedAt: str


class TaskPageOut(BaseModel):
    items: list[TaskOut]
    total: int
    page: int
    pageSize: int


class StatsOut(BaseModel):
    todayDone: int
    queued: int
    published: int
    pendingAlerts: int
    todayDelta: int
    weekDelta: int
