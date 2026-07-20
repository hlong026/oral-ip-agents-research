"""avatar 出入参（白标：不暴露供应商品牌，无公共形象）"""
from pydantic import BaseModel


class AvatarOut(BaseModel):
    id: str
    name: str
    source: str
    avatarType: str  # video | image
    scene: str
    style: str
    coverUrl: str | None
    previewUrl: str | None = None
    status: str
    createdAt: str


class AvatarStatusOut(BaseModel):
    id: str
    status: str
    progress: int = 0  # 0~100
