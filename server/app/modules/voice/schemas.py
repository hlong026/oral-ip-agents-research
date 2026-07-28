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


class CloudVoiceOut(BaseModel):
    """云端历史克隆声音（找回导入用；cloudId 为不透明标识，不暴露供应商品牌）"""

    cloudId: str
    name: str
    imported: bool  # 当前账号是否已导入
    localVoiceId: str | None = None  # 已导入时对应的本地声音 ID


class CloudImportIn(BaseModel):
    cloudId: str
    name: str | None = None  # 缺省用云端名称
    consentToken: str  # 合规红线：导入同样须确认本人授权


class CloneStatusOut(BaseModel):
    id: str
    status: str
    demoUrl: str | None = None  # 克隆完成后返回试听链接


class VoiceEditIn(BaseModel):
    rate: str = "1.0"  # 0.5 ~ 2.0
    volume: str = "1.0"  # 0.1 ~ 2.0
    pitch: str = "1.0"  # 0.1 ~ 2.0


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
