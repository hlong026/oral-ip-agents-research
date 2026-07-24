"""auth 模块 Pydantic 出入参

用户认证策略：
- 禁止通过手机号直接注册，只能通过激活码激活开户
- 激活时绑定手机号 + 密码作为后续登录凭据
- 登录仅支持已激活用户的手机号 + 密码方式
"""

from typing import Literal

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    """手机号 + 密码登录（仅限已激活用户）"""

    phone: str = Field(min_length=5, max_length=20)
    password: str = Field(min_length=6, max_length=64)
    deviceId: str | None = None


class RefreshIn(BaseModel):
    refreshToken: str


class ChangePasswordIn(BaseModel):
    """修改密码（需已登录）"""

    oldPassword: str = Field(min_length=6, max_length=64)
    newPassword: str = Field(min_length=6, max_length=64)


class UpdatePhoneIn(BaseModel):
    """换绑手机号（需已登录 + 验证新手机号未被占用）"""

    newPhone: str = Field(min_length=5, max_length=20)
    password: str = Field(min_length=6, max_length=64, description="当前密码，用于身份确认")


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
    role: Literal["user", "admin", "ops", "finance", "auditor"]
