"""auth 模块 Pydantic 出入参"""

from pydantic import BaseModel, Field


class CodeLoginIn(BaseModel):
    """用户端激活码登录"""

    code: str = Field(min_length=10, max_length=40)
    deviceFingerprint: str = Field(default="", max_length=128)


class AdminLoginIn(BaseModel):
    """管理端手机号+密码登录"""

    phone: str
    password: str
    deviceId: str | None = None


class RefreshIn(BaseModel):
    refreshToken: str
    deviceFingerprint: str = Field(default="", max_length=128)


class TokensOut(BaseModel):
    accessToken: str
    refreshToken: str
    expiresIn: int


class UserOut(BaseModel):
    id: str
    nickname: str
    avatarChar: str
    createdAt: str
    planType: str = "none"
    planExpiresAt: str | None = None
    activatedAt: str | None = None
    deviceBound: bool = False
