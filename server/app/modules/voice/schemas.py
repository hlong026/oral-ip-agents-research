"""voice 出入参（白标：不暴露供应商品牌）"""
from pydantic import BaseModel


class VoiceOut(BaseModel):
    id: str
    name: str
    source: str
    gender: str
    emotion: str
    language: str
    sampleUrl: str | None
    demoUrl: str | None = None  # 试听链接（克隆完成后有值）
    rate: str = "1.0"
    volume: str = "1.0"
    pitch: str = "1.0"
    status: str
    createdAt: str


class CloneStatusOut(BaseModel):
    id: str
    status: str
    demoUrl: str | None = None  # 克隆完成后返回试听链接


class VoiceEditIn(BaseModel):
    rate: str = "1.0"    # 0.5 ~ 2.0
    volume: str = "1.0"  # 0.1 ~ 2.0
    pitch: str = "1.0"   # 0.1 ~ 2.0


class SynthesizeIn(BaseModel):
    voiceId: str
    text: str
    speed: float = 1.0
    quoteId: str | None = None


class WordTsOut(BaseModel):
    word: str
    start: float
    end: float


class SynthesizeOut(BaseModel):
    audioUrl: str
    words: list[WordTsOut]
