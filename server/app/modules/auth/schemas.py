"""auth 模块 Pydantic 出入参"""

from pydantic import BaseModel, Field


class RegisterIn(BaseModel):
    phone: str = Field(min_length=5, max_length=20)
    password: str = Field(min_length=6, max_length=64)
    nickname: str = Field(default="", max_length=64)


class LoginIn(BaseModel):
    phone: str
    password: str
    deviceId: str | None = None


class RefreshIn(BaseModel):
    refreshToken: str


class TokensOut(BaseModel):
    accessToken: str
    refreshToken: str
    expiresIn: int


class UserOut(BaseModel):
    id: str
    phone: str
    nickname: str
    avatarChar: str
    createdAt: str
    planType: str = "none"
    planExpiresAt: str | None = None
    activatedAt: str | None = None
