"""activation 模块 Pydantic 出入参"""

from pydantic import BaseModel, Field

# ---------- 用户侧 ----------


class ActivateIn(BaseModel):
    """激活码注册（首次开户）"""

    code: str = Field(min_length=10, max_length=40)
    phone: str = Field(min_length=5, max_length=20)
    password: str = Field(min_length=6, max_length=64)
    nickname: str = Field(default="", max_length=64)
    deviceFingerprint: str = Field(default="web", max_length=64)


class RedeemIn(BaseModel):
    """已登录用户兑换新码（续费/充值）"""

    code: str = Field(min_length=10, max_length=40)


class ValidateCodeIn(BaseModel):
    """预校验码有效性"""

    code: str = Field(min_length=10, max_length=40)
    deviceFingerprint: str = Field(default="", max_length=64)


class CodeInfoOut(BaseModel):
    """码信息（预校验返回）"""

    valid: bool
    planType: str = ""
    quotaAmount: float = 0
    durationDays: int = 0
    message: str = ""


class ActivateOut(BaseModel):
    """激活注册返回"""

    accessToken: str
    refreshToken: str
    expiresIn: int
    planType: str
    planSkuCode: str = ""
    planExpiresAt: str | None = None
    quotaBalance: float = 0


class RedeemOut(BaseModel):
    """兑换返回"""

    planType: str
    planSkuCode: str = ""
    planExpiresAt: str | None = None
    quotaGranted: float = 0
    newBalance: float = 0


class SubscriptionOut(BaseModel):
    """订阅状态"""

    planType: str
    planSkuCode: str = ""
    planName: str | None = None
    planExpiresAt: str | None = None
    activatedAt: str | None = None
    nextGrantAt: str | None = None
    monthlyPoints: int = 0
    quotaBalance: float = 0


# ---------- 管理侧 ----------


class BatchCreateIn(BaseModel):
    """批量生成激活码"""

    name: str = Field(default="", max_length=64)
    skuVersionId: str = Field(min_length=1)
    planType: str = Field(default="monthly")
    quotaAmount: float = Field(default=5000, gt=0)
    durationDays: int = Field(default=30, ge=0)
    count: int = Field(default=10, ge=1, le=1000)
    channel: str = Field(default="", max_length=32)
    codeExpiresAt: str | None = None


class BatchOut(BaseModel):
    """批次信息"""

    id: str
    name: str
    planType: str
    quotaAmount: float
    durationDays: int
    totalCount: int
    usedCount: int
    channel: str
    createdAt: str


class CodeOut(BaseModel):
    """码信息（管理端）"""

    id: str
    code: str
    planType: str
    quotaAmount: float
    durationDays: int
    status: str
    channel: str
    boundUserId: str | None = None
    activatedAt: str | None = None
    expiresAt: str | None = None
    createdAt: str


class BatchGenerateOut(BaseModel):
    """批量生成返回"""

    batchId: str
    generated: int
    codes: list[str]


class CodeStatsOut(BaseModel):
    """码统计"""

    total: int = 0
    unused: int = 0
    used: int = 0
    expired: int = 0
    revoked: int = 0
