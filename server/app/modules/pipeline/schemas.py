"""pipeline 出入参"""

from pydantic import BaseModel


class CreatePipelineIn(BaseModel):
    ipId: str
    sourceUrl: str | None = None
    topic: str | None = None
    scriptText: str | None = None
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


class TaskOut(BaseModel):
    id: str
    ipId: str
    title: str
    coverUrl: str | None = None
    sourceUrl: str
    mode: str
    status: str
    steps: list[StepStateOut]
    currentStep: str | None = None
    compute: str
    quotaCost: float
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
