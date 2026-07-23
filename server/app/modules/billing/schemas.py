"""billing 出入参"""

from pydantic import BaseModel, Field


class QuotaOut(BaseModel):
    balance: float
    usedThisMonth: float
    total: float


class UsageItemOut(BaseModel):
    id: str
    traceId: str
    step: str
    resolution: str
    points: float
    compute: str
    createdAt: str


class UsagePageOut(BaseModel):
    items: list[UsageItemOut]
    total: int
    page: int
    pageSize: int


class LedgerItemOut(BaseModel):
    id: str
    eventType: str
    pointsDelta: int
    referenceType: str
    referenceId: str
    taskId: str = ""
    detail: dict | None = None
    createdBy: str = "system"
    createdAt: str


class LedgerPageOut(BaseModel):
    items: list[LedgerItemOut]
    total: int
    page: int
    pageSize: int


class PricePreviewItemIn(BaseModel):
    module: str
    quantity: int = Field(gt=0)


class PricePreviewIn(BaseModel):
    items: list[PricePreviewItemIn] = Field(min_length=1, max_length=20)


class ReservationCreateIn(BaseModel):
    quoteId: str
    count: int = Field(default=1, ge=1, le=20)


class ReservationItemOut(BaseModel):
    id: str
    quoteId: str
    reservedPoints: int
    status: str


class ReservationBatchOut(BaseModel):
    items: list[ReservationItemOut]
    availablePoints: float


class ReservationStateOut(BaseModel):
    id: str
    status: str
    reservedPoints: int
    actualPoints: int
    availablePoints: float
