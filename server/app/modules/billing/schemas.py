"""billing 出入参"""
from pydantic import BaseModel


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
