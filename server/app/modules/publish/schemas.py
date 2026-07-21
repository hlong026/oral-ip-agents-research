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


class PublishIn(BaseModel):
    taskId: str | None = None
    platforms: list[str]
    title: str
    topics: list[str] = []
    videoKey: str
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
    videoUrl: str | None = None
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
