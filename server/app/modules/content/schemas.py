"""content 出入参（F-101~F-106）"""

from pydantic import BaseModel, Field


class ParseIn(BaseModel):
    url: str | None = None
    videoId: str | None = None  # 视频ID（与 platform 配合使用）
    platform: str | None = None  # douyin | xiaohongshu（videoId 时必填）
    quoteId: str | None = None


class ProbeUrlIn(BaseModel):
    url: str = Field(min_length=1, max_length=2_000)


class ProbeUrlOut(BaseModel):
    durationSeconds: float


class WordTsOut(BaseModel):
    word: str
    start: float
    end: float


class TranscriptOut(BaseModel):
    text: str
    words: list[WordTsOut]
    duration: float
    language: str = "zh"


class ParseOut(BaseModel):
    transcript: TranscriptOut | None
    degraded: bool
    platform: str | None = None
    title: str | None = None
    scriptId: str | None = None
    cover: str | None = None  # 封面URL
    author: dict | None = None  # 作者信息（platform=1时有效）


class RewriteIn(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)
    intensity: str = "structure"  # light | structure | theme（F-103 三档）
    prompt: str | None = Field(default=None, max_length=4_000)
    scriptId: str | None = None
    quoteId: str | None = None


class RewriteOut(BaseModel):
    text: str
    structure: dict | None = None  # Stage 1 拆解结果（light模式不返回）
    outline: str | None = None  # Stage 2 大纲（light模式不返回）
    similarity: float | None = None  # 去重分
    validationPassed: bool = True  # 校验是否通过


class SimilarityIn(BaseModel):
    text: str
    quoteId: str | None = None


class SpanOut(BaseModel):
    text: str
    start: int
    end: int


class SimilarityOut(BaseModel):
    score: float
    duplicatedSpans: list[SpanOut]


class TopicsIn(BaseModel):
    keyword: str
    quoteId: str | None = None


class TopicsOut(BaseModel):
    topics: list[str]


class ScriptCreateIn(BaseModel):
    """手动创建文案资产（选题生成 / 直接编写入口落库）"""

    title: str = ""
    text: str
    platform: str = "manual"  # manual 直写 | topic 选题生成
    topic: str | None = None


class ScriptOut(BaseModel):
    id: str
    title: str
    sourceUrl: str
    platform: str
    originalText: str
    rewrittenText: str
    similarityScore: float
    status: str
    createdAt: str
