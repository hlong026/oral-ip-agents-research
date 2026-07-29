"""pipeline 出入参"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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
    platforms: list[str] = Field(default_factory=list)
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
    artifacts: dict[str, str] = Field(default_factory=dict)
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
    # 字幕开关：关闭时重合成跳过 ASS 烧录，输出无字幕成片；样式配置保留，便于随时重新开启
    subtitleEnabled: bool = True
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
    quality: dict[str, object] = Field(default_factory=dict)
    error: str = ""
    isActive: bool
    createdAt: str
    updatedAt: str


class PublicationSubtitleSegmentIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    startMs: int = Field(ge=0)
    endMs: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_time_range(self) -> "PublicationSubtitleSegmentIn":
        if self.endMs <= self.startMs:
            raise ValueError("endMs must be greater than startMs")
        return self


class PublicationStyleIn(BaseModel):
    fontFamily: Literal["Noto Sans CJK SC", "Source Han Sans SC", "PingFang SC"] = "Noto Sans CJK SC"
    fontSize: int = Field(default=44, ge=32, le=64)
    color: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    stroke: int = Field(default=3, ge=0, le=6)
    xPercent: int = Field(default=50, ge=0, le=100)
    yPercent: int = Field(default=82, ge=0, le=100)


class PublicationSubtitlesIn(BaseModel):
    enabled: bool = True
    source: Literal["asr_aligned", "tts_fallback", "manual"] = "manual"
    segments: list[PublicationSubtitleSegmentIn] = Field(default_factory=list)
    style: PublicationStyleIn = Field(default_factory=PublicationStyleIn)


class PublicationCoverIn(BaseModel):
    selectedFrameMs: int = Field(default=1500, ge=0, le=3000)
    template: Literal["bold-bottom", "center-band", "top-title", "none"] = "bold-bottom"
    text: str = Field(default="", max_length=40)


class PublicationContentIn(BaseModel):
    schemaVersion: Literal[1] = 1
    title: str = Field(min_length=1, max_length=128)
    topics: list[str] = Field(default_factory=list, max_length=8)
    subtitles: PublicationSubtitlesIn = Field(default_factory=PublicationSubtitlesIn)
    cover: PublicationCoverIn = Field(default_factory=PublicationCoverIn)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("title must not be blank")
        return cleaned

    @model_validator(mode="after")
    def normalize_topics(self) -> "PublicationContentIn":
        self.topics = [item.strip() for item in self.topics if item.strip()][:8]
        return self


class PublicationDraftPutIn(BaseModel):
    draftRevision: int = Field(ge=1)
    content: PublicationContentIn


class PublicationFinalizeIn(BaseModel):
    quoteId: str
    idempotencyKey: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")
    draftRevision: int = Field(ge=1)


class PublicationRevisionOut(BaseModel):
    id: str
    taskId: str
    revision: int
    status: str
    baseRenderVersionId: str = ""
    renderVersionId: str = ""
    content: PublicationContentIn
    draftRevision: int
    lastError: str = ""
    finalizedAt: str | None = None
    createdAt: str
    updatedAt: str


class CoverCandidateOut(BaseModel):
    timestampMs: int
    imageUrl: str


class MetadataSuggestionGroupOut(BaseModel):
    title: str
    tags: list[str]
    coverText: str = ""


class MetadataSuggestionsOut(BaseModel):
    titles: list[str]
    tags: list[str]
    groups: list[MetadataSuggestionGroupOut] = Field(default_factory=list)


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
    artifacts: dict[str, object] = Field(default_factory=dict)
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
