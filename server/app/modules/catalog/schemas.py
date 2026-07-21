"""套餐 SKU 与模块积分价格出入参。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

BillingUnit = Literal[
    "per_action",
    "per_minute",
    "per_second",
    "per_1k_chars",
    "per_1k_tokens",
    "per_image",
    "per_asset",
]


class PlanCreateIn(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    subtitle: str = Field(default="", max_length=128)
    description: str = ""
    badge: str = Field(default="", max_length=32)
    sortOrder: int = 0
    skuType: Literal["trial", "annual_bundle", "internal_annual", "points_pack"] = "annual_bundle"
    audience: Literal["public", "internal"] = "public"
    durationDays: int = Field(default=365, ge=0)
    monthlyPoints: int = Field(default=0, ge=0)
    oneTimePoints: int = Field(default=0, ge=0)
    listPriceCents: int = Field(default=0, ge=0)
    displayPriceCents: int = Field(default=0, ge=0)
    entitlements: list[str] = Field(default_factory=list)
    maxConcurrency: int = Field(default=1, ge=1)
    maxResolution: str = "1080p"
    purchaseInstructions: str = ""

    @model_validator(mode="after")
    def validate_sku_economics(self):
        if self.skuType == "internal_annual" and self.audience != "internal":
            raise ValueError("内部员工套餐必须使用 internal 范围")
        if self.skuType == "points_pack":
            if self.durationDays != 0 or self.monthlyPoints != 0 or self.oneTimePoints <= 0:
                raise ValueError("积分包必须为 0 服务天数、0 月度积分且一次性积分大于 0")
        return self


class PlanOut(BaseModel):
    id: str
    code: str
    version: int
    status: str
    name: str
    subtitle: str = ""
    description: str = ""
    badge: str = ""
    sortOrder: int = 0
    skuType: str
    audience: str
    durationDays: int
    monthlyPoints: int
    oneTimePoints: int
    listPriceCents: int
    displayPriceCents: int
    entitlements: list[str]
    maxConcurrency: int
    maxResolution: str
    purchaseInstructions: str = ""
    effectiveAt: datetime | None = None
    publishedAt: datetime | None = None
    retiredAt: datetime | None = None


class PublishIn(BaseModel):
    effectiveAt: datetime | None = None


class PriceVersionCreateIn(BaseModel):
    version: str = Field(min_length=1, max_length=64)


class PriceVersionOut(BaseModel):
    id: str
    version: str
    status: str
    effectiveAt: datetime | None = None
    publishedAt: datetime | None = None
    retiredAt: datetime | None = None


class ModulePriceIn(BaseModel):
    displayName: str = Field(min_length=1, max_length=64)
    billingUnit: BillingUnit
    unitSize: int = Field(default=1, ge=1)
    pointsPerUnit: int = Field(default=0, ge=0)
    minimumPoints: int = Field(default=0, ge=0)
    enabled: bool = True
    publicDescription: str = ""
    internalCostCentsPerUnit: int = Field(default=0, ge=0)
    targetMarginBps: int = Field(default=0, ge=0, le=10000)

    @model_validator(mode="after")
    def enabled_prices_must_be_positive(self):
        if self.enabled and self.pointsPerUnit <= 0:
            raise ValueError("启用模块的每单位积分必须大于 0")
        return self


class ModulePriceAdminOut(ModulePriceIn):
    module: str


class ModulePricePublicOut(BaseModel):
    module: str
    displayName: str
    billingUnit: str
    unitSize: int
    pointsPerUnit: int
    minimumPoints: int
    publicDescription: str


class ModulePriceCatalogOut(BaseModel):
    version: str
    updatedAt: datetime | None = None
    items: list[ModulePricePublicOut]
