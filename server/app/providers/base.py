"""
Provider 抽象层（06 文档 §10.3）：七类 Protocol，防供应商锁定。
- clone() 均强制 consent_token（合规红线）
- 降级链：主实现异常 → StepRecoverableError → registry 换实现重试，降级事件任务中心可见
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderError(Exception):
    """Provider 调用失败"""


class StepRecoverableError(ProviderError):
    """可降级重试的错误（触发降级链）"""


class ConsentRequiredError(ProviderError):
    """缺少本人授权凭证（合规红线，不可降级）"""


@dataclass
class WordTs:
    word: str
    start: float
    end: float


@dataclass
class TranscriptResult:
    text: str
    words: list[WordTs]
    duration: float
    language: str = "zh"


@dataclass
class ParseResult:
    platform: str
    title: str
    video_key: str | None = None  # 去水印视频存储 key
    degraded: bool = False  # 是否走了降级（手动上传/粘贴）


@dataclass
class SimilarityResult:
    score: float  # 0-100
    duplicated_spans: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SynthesizeResult:
    audio_key: str
    words: list[WordTs]
    duration: float


class LLMProvider(Protocol):
    name: str

    async def rewrite(self, text: str, intensity: str, prompt: str | None = None) -> str: ...
    async def generate_topics(self, keyword: str, count: int = 5) -> list[str]: ...
    async def check_similarity(self, text: str) -> SimilarityResult: ...
    async def generate_titles(self, script: str, platform: str, count: int = 3) -> list[str]: ...
    # ---- 三阶段仿写引擎 ----
    async def analyze_structure(self, text: str, mode: str = "full") -> dict: ...
    async def generate_outline(self, structure: dict, persona_ctx: str, intensity: str, duration: int = 60) -> str: ...
    async def generate_script(self, outline: str, persona_ctx: str, constraints: dict) -> str: ...
    async def polish_light(self, text: str, persona_ctx: str) -> str: ...
    async def validation_rewrite(self, script: str, persona_ctx: str, issues: str) -> str: ...


class ParseProvider(Protocol):
    name: str

    async def parse_url(self, url: str) -> ParseResult: ...


class ASRProvider(Protocol):
    name: str

    async def transcribe(self, video_key: str, duration_sec: float | None = None) -> TranscriptResult: ...


class VoiceProvider(Protocol):
    name: str

    async def clone(self, name: str, sample_key: str, consent_token: str, language: str = "zh") -> str: ...
    async def query_clone_task(self, task_id: str) -> dict[str, Any]: ...
    async def synthesize(self, voice_id: str, text: str, speed: float = 1.0) -> SynthesizeResult: ...
    async def list_voices(self) -> list[dict[str, Any]]: ...


class AvatarProvider(Protocol):
    name: str

    async def clone_by_video(self, name: str, video_key: str, consent_token: str) -> str: ...
    async def clone_by_image(self, name: str, image_key: str, model: int = 2) -> str: ...
    async def query_avatar_task(self, task_id: str) -> dict[str, Any]: ...
    async def create_by_audio(self, avatar_id: str, audio_key: str) -> str: ...
    async def create_by_tts(
        self, avatar_id: str, voice_id: str, text: str, subtitle_opts: dict[str, Any] | None = None
    ) -> str: ...
    async def query_video_task(self, task_id: str) -> dict[str, Any]: ...
    async def poll_video_task(self, task_id: str) -> dict[str, Any]: ...
    async def download_video(self, temp_url: str) -> str: ...
    async def list_public(self) -> list[dict[str, Any]]: ...


@dataclass
class ComposeInput:
    video_key: str
    audio_key: str | None
    subtitle_words: list[WordTs]
    subtitle_style: dict[str, Any]
    bgm_key: str | None
    bgm_mode: str  # auto | custom | off
    cover_text: str
    ratio: str = "9:16"
    randomize: bool = False  # 差异化参数随机化（变速/镜像/抽帧，C5）


@dataclass
class ComposeResult:
    video_key: str
    cover_key: str
    duration: float


class ComposeEngine(Protocol):
    name: str

    async def compose(self, inp: ComposeInput) -> ComposeResult: ...


class PublishDriver(Protocol):
    name: str
    platform: str

    async def qrcode_login(self) -> dict[str, str]: ...  # {qrcodeUrl, ticket}
    async def check_login(self, ticket: str) -> dict[str, Any] | None: ...
    async def publish(
        self,
        account_session: dict[str, Any],
        video_key: str,
        title: str,
        topics: list[str],
        cover_key: str | None,
        scheduled_at: str | None = None,
        account_id: str = "",
    ) -> str: ...
