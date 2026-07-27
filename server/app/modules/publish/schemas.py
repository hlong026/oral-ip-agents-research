"""publish 出入参"""

from pydantic import BaseModel


class AccountOut(BaseModel):
    id: str
    platform: str
    platformName: str
    nickname: str
    status: str  # active | expired
    createdAt: str


class QrcodeStartOut(BaseModel):
    ticket: str
    qrcodeUrl: str


class AccountUpdateIn(BaseModel):
    nickname: str


class QrcodePollOut(BaseModel):
    status: str  # waiting | success | expired
    account: AccountOut | None = None
    qrcodeUrl: str | None = None  # 等待中透传最新二维码（过期自动刷新后前端同步换图）
    message: str | None = None


class PublishIn(BaseModel):
    taskId: str
    platforms: list[str]
    title: str
    topics: list[str] = []
    # 兼容旧客户端回传，但服务端只信任任务中已登记的产物 key。
    videoKey: str | None = None
    coverKey: str | None = None
    publishAt: str | None = None


class JobOut(BaseModel):
    id: str
    taskId: str
    platform: str
    platformName: str
    accountId: str
    accountNickname: str = ""
    title: str
    status: str
    scheduledAt: str | None = None
    error: str = ""
    postId: str = ""
    # post_id 语义澄清：internal=内部追踪号（非平台作品 ID）| platform=平台真实作品 ID | 空=未发布
    postIdSource: str = ""
    videoUrl: str | None = None
    packageUrl: str | None = None
    retryCount: int = 0
    createdAt: str
    updatedAt: str


class JobPageOut(BaseModel):
    items: list[JobOut]
    total: int
    page: int
    pageSize: int


class ExportOut(BaseModel):
    jobId: str
    videoUrl: str
    packageKey: str
    packageUrl: str
    metadata: dict[str, object]


class PublishCapabilityOut(BaseModel):
    platform: str
    platformName: str
    mode: str  # automatic | semi_automatic | export_only | development_mock
    verificationStatus: str  # verified | unverified | development_mock
    automaticEnabled: bool
    fallback: str = "manual_package"
    reason: str = ""
