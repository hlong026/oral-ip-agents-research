"""
Mock Provider 实现（PROVIDER_MODE=mock，开箱即用端到端演示）
- 模拟供应商延迟与产物形态；接入真实供应商仅需 .env 切换 PROVIDER_MODE=real
"""

import asyncio
import math
import struct
import uuid
from typing import Any

from app.core.storage import save_bytes, save_text

from .base import (
    ComposeInput,
    ComposeResult,
    ParseResult,
    SimilarityResult,
    SynthesizeResult,
    TranscriptResult,
    WordTs,
)

MOCK_SCRIPT = (
    "你知道吗？百分之九十的个体户，都在多交冤枉税。今天我用三分钟，"
    "把小规模纳税人最容易踩的三个坑讲清楚。第一，季度三十万免税额度，"
    "是普票额度，专票部分照样要交。第二，核定征收不是想选就能选，"
    "要看行业利润率。第三，开票软件里的税收分类编码，选错了就是虚开风险。"
    "把这条视频收藏起来，报税的时候对照着看，至少帮你省下一部手机钱。"
)


def _words_for(text: str, per_char: float = 0.28) -> list[WordTs]:
    words: list[WordTs] = []
    t = 0.0
    for ch in text:
        if ch.strip():
            words.append(WordTs(word=ch, start=round(t, 2), end=round(t + per_char, 2)))
            t += per_char
    return words


def _sine_wav(duration: float, freq: float = 220.0, rate: int = 16000) -> bytes:
    """生成可播放的示例音频（真实 WAV，供试听/合成链路联调）"""
    n = int(duration * rate)
    frames = bytearray()
    for i in range(n):
        # 叠加两个谐波，听感接近"蜂鸣人声占位"
        v = 0.28 * math.sin(2 * math.pi * freq * i / rate) + 0.12 * math.sin(2 * math.pi * freq * 2 * i / rate)
        frames += struct.pack("<h", int(v * 32767))
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(frames))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
        + b"data"
        + struct.pack("<I", len(frames))
    )
    return bytes(header) + bytes(frames)


class MockLLM:
    name = "mock-llm"

    async def rewrite(self, text: str, intensity: str, prompt: str | None = None) -> str:
        await asyncio.sleep(1.2)
        prefix = {"light": "【轻度润色】", "structure": "【结构重写】", "theme": "【主题创作】"}.get(intensity, "")
        body = text.strip() or MOCK_SCRIPT
        if prompt:
            return f"{prefix}（按指令：{prompt[:20]}）\n{body}"
        return f"{prefix}\n{body}"

    async def generate_topics(self, keyword: str, count: int = 5) -> list[str]:
        await asyncio.sleep(0.8)
        return [f"{keyword}：新手最容易忽略的第 {i + 1} 件事" for i in range(count)]

    async def check_similarity(self, text: str, reference_text: str | None = None) -> SimilarityResult:
        await asyncio.sleep(0.6)
        score = 100.0 if reference_text and text.strip() == reference_text.strip() else float(30 + len(text) % 55)
        spans = []
        if score > 60 and len(text) > 20:
            spans = [{"text": text[:20], "start": 0, "end": 20}]
        return SimilarityResult(score=score, duplicated_spans=spans)

    async def generate_titles(self, script: str, platform: str, count: int = 3) -> list[str]:
        await asyncio.sleep(0.5)
        base = script.strip()[:12] or "口播干货"
        return [f"{base}，第 {i + 1} 点最关键 #{platform} 干货" for i in range(count)]

    # ---- 三阶段仿写引擎 Mock ----

    async def analyze_structure(self, text: str, mode: str = "full") -> dict:
        await asyncio.sleep(0.8)
        if mode == "theme":
            return {
                "topic_keywords": ["财税", "个体户", "免税额度"],
                "core_message": "个体户常见税务误区解析",
                "target_emotion": "焦虑",
            }
        return {
            "hook_type": "数据震撼",
            "hook_text": "你知道吗？百分之九十的个体户，都在多交冒枉税。",
            "pain_points": ["多交税", "不懂政策"],
            "value_points": ["季度30万免税额度解析", "核定征收条件", "税收分类编码风险"],
            "cta_type": "关注收藏",
            "cta_text": "把这条视频收藏起来，报税的时候对照着看。",
            "emotion_curve": "震惊→焦虑→豁然→行动",
            "rhythm": "层层递进",
            "estimated_duration": 60,
            "topic_keywords": ["个体户", "税务", "免税额度"],
        }

    async def generate_outline(self, structure: dict, persona_ctx: str, intensity: str, duration: int = 60) -> str:
        await asyncio.sleep(1.0)
        return (
            "[钩子] 你知道吗，九成的老板都在多交税\n"
            "[痛点] 很多人根本不知道自己多交了哪些钱\n"
            "[干货1] 第一个坑：免税额度的正确理解\n"
            "[干货2] 第二个坑：征收方式不是想选就能选\n"
            "[干货3] 第三个坑：开票编码选错的后果\n"
            "[CTA] 收藏起来对照着看，至少省一部手机钱"
        )

    async def generate_script(self, outline: str, persona_ctx: str, constraints: dict) -> str:
        await asyncio.sleep(1.2)
        return MOCK_SCRIPT

    async def generate_script_variant(
        self,
        outline: str,
        persona_ctx: str,
        constraints: dict,
        temperature: float,
        strategy: str,
    ) -> str:
        await asyncio.sleep(0.2)
        return f"【{strategy} · {temperature:.1f}】\n{MOCK_SCRIPT}"

    async def polish_light(self, text: str, persona_ctx: str) -> str:
        await asyncio.sleep(0.8)
        return f"【人设润色】\n{text.strip()}"

    async def validation_rewrite(self, script: str, persona_ctx: str, issues: str) -> str:
        await asyncio.sleep(0.8)
        return f"【已修正】\n{script.strip()}"


class MockParser:
    name = "mock-parse"

    async def parse_url(self, url: str) -> ParseResult:
        await asyncio.sleep(1.0)
        platform = "douyin"
        for p, keys in {
            "douyin": ["douyin", "iesdouyin"],
            "kuaishou": ["kuaishou", "gifshow"],
            "xiaohongshu": ["xiaohongshu", "xhslink"],
        }.items():
            if any(k in url.lower() for k in keys):
                platform = p
                break
        # 生成占位"去水印视频"（实为文本占位，供合成链路 trace）
        key = await save_text("parsed", "video.mp4.txt", f"MOCK VIDEO parsed from {url}")
        return ParseResult(platform=platform, title="3 个技巧让口播不冷场", video_key=key)


class MockASR:
    name = "mock-faster-whisper"

    async def transcribe(self, video_key: str, duration_sec: float | None = None) -> TranscriptResult:
        await asyncio.sleep(1.5)
        words = _words_for(MOCK_SCRIPT)
        return TranscriptResult(text=MOCK_SCRIPT, words=words, duration=round(len(MOCK_SCRIPT) * 0.28, 1))


class MockVoice:
    name = "mock-voice"

    async def clone(self, name: str, sample_key: str, consent_token: str, language: str = "zh") -> str:
        await asyncio.sleep(2.0)
        return f"mock_task_{uuid.uuid4().hex[:12]}"

    async def query_clone_task(self, task_id: str) -> dict[str, Any]:
        await asyncio.sleep(0.5)
        # Mock: 直接返回完成 + 试听链接
        key = await save_bytes("voice-demos", "demo.wav", _sine_wav(3.0))
        return {
            "status": 3,
            "voice_id": f"mock_voice_{uuid.uuid4().hex[:10]}",
            "demo_url": f"/media/{key}",
        }

    async def synthesize(self, voice_id: str, text: str, speed: float = 1.0) -> SynthesizeResult:
        await asyncio.sleep(1.5)
        words = _words_for(text, per_char=0.28 / max(speed, 0.5))
        duration = words[-1].end if words else 5.0
        key = await save_bytes("tts", "audio.wav", _sine_wav(min(duration, 30.0)))
        return SynthesizeResult(audio_key=key, words=words, duration=duration)

    async def list_voices(self) -> list[dict[str, Any]]:
        return []


class MockAvatar:
    name = "mock-avatar"

    async def clone_by_video(self, name: str, video_key: str, consent_token: str) -> str:
        await asyncio.sleep(2.5)
        return f"mock_task_{uuid.uuid4().hex[:12]}"

    async def clone_by_image(self, name: str, image_key: str, model: int = 2) -> str:
        await asyncio.sleep(2.0)
        return f"mock_task_{uuid.uuid4().hex[:12]}"

    async def query_avatar_task(self, task_id: str) -> dict[str, Any]:
        await asyncio.sleep(1.0)
        return {"status": 3, "avatar_id": f"mock_avatar_{uuid.uuid4().hex[:10]}"}

    async def create_by_audio(self, avatar_id: str, audio_key: str) -> str:
        await asyncio.sleep(0.5)
        return f"mock_render_{uuid.uuid4().hex[:12]}"

    async def create_by_tts(
        self, avatar_id: str, voice_id: str, text: str, subtitle_opts: dict[str, Any] | None = None
    ) -> str:
        await asyncio.sleep(0.5)
        return f"mock_render_{uuid.uuid4().hex[:12]}"

    async def query_video_task(self, task_id: str) -> dict[str, Any]:
        await asyncio.sleep(1.0)
        key = await save_text("avatar-videos", "render.mp4.txt", f"MOCK VIDEO for {task_id}")
        return {"status": 3, "video_url": f"/media/{key}", "duration": 30}

    async def poll_video_task(self, task_id: str) -> dict[str, Any]:
        return await self.query_video_task(task_id)

    async def download_video(self, temp_url: str) -> str:
        key = await save_text("avatar-videos", "video.mp4.txt", f"MOCK VIDEO {temp_url}")
        return key

    async def list_public(self) -> list[dict[str, Any]]:
        return []


class MockCompose:
    name = "mock-ffmpeg"

    async def compose(self, inp: ComposeInput) -> ComposeResult:
        await asyncio.sleep(2.0)
        note = (
            f"MOCK COMPOSE 1080P {inp.ratio}\nvideo={inp.video_key}\naudio={inp.audio_key}\n"
            f"subtitles={len(inp.subtitle_words)} words style={inp.subtitle_style}\n"
            f"bgm={inp.bgm_mode} randomize={inp.randomize}\ncover_text={inp.cover_text}\n"
        )
        video_key = await save_text("compose", "final.mp4.txt", note)
        cover_key = await save_text("compose", "cover.jpg.txt", f"MOCK COVER: {inp.cover_text}")
        return ComposeResult(video_key=video_key, cover_key=cover_key, duration=float(len(inp.subtitle_words) * 0.28))


class MockPublishDriver:
    """social-auto-upload 二开的占位实现（G1 预研结论落地前）"""

    def __init__(self, platform: str):
        self.platform = platform
        self.name = f"mock-sau-{platform}"
        self._tickets: dict[str, dict[str, Any]] = {}

    async def qrcode_login(self) -> dict[str, str]:
        ticket = uuid.uuid4().hex
        self._tickets[ticket] = {"scanned": False}
        return {"qrcodeUrl": f"https://mock.qr/{self.platform}/{ticket}", "ticket": ticket}

    async def check_login(self, ticket: str) -> dict[str, Any] | None:
        # Mock：第二次轮询视为已扫码
        state = self._tickets.get(ticket)
        if state is None:
            return None
        if not state["scanned"]:
            state["scanned"] = True
            return None
        return {"sessionId": uuid.uuid4().hex, "nickname": f"{self.platform} 运营号", "platform": self.platform}

    async def publish(
        self,
        account_session: dict[str, Any],
        video_key: str,
        title: str,
        topics: list[str],
        cover_key: str | None,
        scheduled_at: str | None = None,
        account_id: str = "",
    ) -> str:
        await asyncio.sleep(1.5)
        return f"mock_post_{self.platform}_{uuid.uuid4().hex[:8]}"
