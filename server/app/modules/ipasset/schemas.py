"""ipasset 出入参"""

from pydantic import BaseModel, Field


class PersonaIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    domain: str = "知识科普"
    tone: str = "专业、接地气"
    values: str = ""
    tabooWords: list[str] = []
    audience: str = ""
    contentPillars: list[str] = []
    styleSamples: str = ""
    catchphrase: str = ""
    videoDuration: int = 60
    ctaStyle: str = ""
    avoidTopics: list[str] = []


class PersonaUpdate(BaseModel):
    name: str | None = None
    domain: str | None = None
    tone: str | None = None
    values: str | None = None
    tabooWords: list[str] | None = None
    voiceId: str | None = None
    avatarId: str | None = None
    audience: str | None = None
    contentPillars: list[str] | None = None
    styleSamples: str | None = None
    catchphrase: str | None = None
    videoDuration: int | None = None
    ctaStyle: str | None = None
    avoidTopics: list[str] | None = None


class PersonaOut(BaseModel):
    id: str
    name: str
    domain: str
    tone: str
    values: str
    tabooWords: list[str]
    avatarChar: str
    avatarGrad: str
    voiceId: str | None
    avatarId: str | None
    isActive: bool
    audience: str = ""
    contentPillars: list[str] = []
    styleSamples: str = ""
    catchphrase: str = ""
    videoDuration: int = 60
    ctaStyle: str = ""
    avoidTopics: list[str] = []
