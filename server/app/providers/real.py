"""
真实 Provider 实现骨架
- DeepSeek（LLM 主力，OpenAI 兼容协议）
- 声音克隆 + 数字人已迁移到 hifly.py（HiFlyVoice / HiFlyAvatar）
- 超时 30s + 重试 2 次（tenacity），失败抛 StepRecoverableError 触发降级链
- 凭据从前端设置页动态读取（dynamic_config），保存即时生效无需重启
"""
import json as _json
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.core.dynamic_config import get_config

from .base import (
    ComposeInput,
    ComposeResult,
    ParseResult,
    SimilarityResult,
    StepRecoverableError,
)
from .mock import MockCompose, MockLLM, MockParser

settings = get_settings()
TIMEOUT = httpx.Timeout(30.0)


class DeepSeekLLM:
    """DeepSeek-V3 主力（openai SDK 兼容协议）；凭据从前端设置页动态读取"""

    name = "deepseek-v3"

    def __init__(self) -> None:
        self._mock = MockLLM()
        self._client: httpx.AsyncClient | None = None
        self._client_key: str = ""  # 用于检测凭据变更时重建 client

    async def _get_client(self) -> httpx.AsyncClient:
        """动态获取 HTTP 客户端（凭据变更时自动重建）"""
        api_key = await get_config("deepseek_api_key")
        base_url = await get_config("deepseek_base_url", "https://api.deepseek.com/v1")
        if not api_key:
            raise StepRecoverableError("deepseek key 未配置，请在设置页填写")
        # 凭据变更时重建 client
        if self._client is None or self._client_key != api_key:
            if self._client:
                await self._client.aclose()
            self._client = httpx.AsyncClient(
                base_url=base_url,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=TIMEOUT,
            )
            self._client_key = api_key
        return self._client

    async def _get_model(self) -> str:
        return await get_config("deepseek_model", "deepseek-chat")

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=8))
    async def _chat(self, system: str, user: str) -> str:
        client = await self._get_client()
        model = await self._get_model()
        try:
            resp = await client.post(
                "/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.8,
                },
            )
            resp.raise_for_status()
            return str(resp.json()["choices"][0]["message"]["content"])
        except httpx.HTTPError as e:
            raise StepRecoverableError(f"deepseek 调用失败: {e}") from e

    async def rewrite(self, text: str, intensity: str, prompt: str | None = None) -> str:
        level = {"light": "轻度润色，保持原意", "structure": "保留结构，语义级重写",
                 "theme": "只借鉴主题，完全重新创作"}.get(intensity, "轻度润色")
        sys = "你是爆款口播文案专家。仿写要求：口语化、有钩子、无抄袭风险。"
        extra = f"\n额外指令：{prompt}" if prompt else ""
        return await self._chat(sys, f"请对以下文案进行{level}：\n{text}{extra}")

    async def generate_topics(self, keyword: str, count: int = 5) -> list[str]:
        raw = await self._chat("你是短视频选题策划", f"围绕「{keyword}」生成 {count} 个爆款口播选题，每行一个")
        return [line.strip(" 0123456789.、") for line in raw.splitlines() if line.strip()][:count]

    async def check_similarity(self, text: str) -> SimilarityResult:
        # Embedding（BGE-M3）+ n-gram 双指标在 content 模块本地计算；LLM 不直接承担
        return await self._mock.check_similarity(text)

    async def generate_titles(self, script: str, platform: str, count: int = 3) -> list[str]:
        raw = await self._chat("你是短视频标题党（合规版）",
                               f"为以下口播稿生成 {count} 组适配{platform}风格的标题+话题标签：\n{script[:400]}")
        return [line.strip() for line in raw.splitlines() if line.strip()][:count]

    # ---- 三阶段仿写引擎 ----

    async def analyze_structure(self, text: str, mode: str = "full") -> dict:
        from app.modules.content.prompts import (
            STRUCTURE_ANALYSIS_SYSTEM,
            STRUCTURE_ANALYSIS_USER,
            THEME_EXTRACTION_SYSTEM,
            THEME_EXTRACTION_USER,
        )
        if mode == "theme":
            raw = await self._chat(THEME_EXTRACTION_SYSTEM, THEME_EXTRACTION_USER.format(text=text))
        else:
            raw = await self._chat(STRUCTURE_ANALYSIS_SYSTEM, STRUCTURE_ANALYSIS_USER.format(text=text))
        return _parse_json(raw)

    async def generate_outline(self, structure: dict, persona_ctx: str, intensity: str, duration: int = 60) -> str:
        from app.modules.content.prompts import (
            OUTLINE_GENERATION_SYSTEM,
            OUTLINE_GENERATION_USER,
            OUTLINE_THEME_SYSTEM,
            OUTLINE_THEME_USER,
        )
        if intensity == "theme":
            topic = "、".join(structure.get("topic_keywords", ["口播干货"]))
            user = OUTLINE_THEME_USER.format(persona_ctx=persona_ctx, topic=topic, duration=duration)
            return await self._chat(OUTLINE_THEME_SYSTEM, user)
        user = OUTLINE_GENERATION_USER.format(
            persona_ctx=persona_ctx,
            hook_type=structure.get("hook_type", "提问"),
            hook_text=structure.get("hook_text", ""),
            pain_points="、".join(structure.get("pain_points", [])),
            value_points="、".join(structure.get("value_points", [])),
            cta_type=structure.get("cta_type", "关注收藏"),
            cta_text=structure.get("cta_text", ""),
            emotion_curve=structure.get("emotion_curve", "层层递进"),
            rhythm=structure.get("rhythm", "娓娓道来"),
            duration=duration,
        )
        return await self._chat(OUTLINE_GENERATION_SYSTEM, user)

    async def generate_script(self, outline: str, persona_ctx: str, constraints: dict) -> str:
        from app.modules.content.prompts import SCRIPT_GENERATION_SYSTEM, SCRIPT_GENERATION_USER
        duration = constraints.get("duration", 60)
        word_count = int(duration * 3.5)
        user = SCRIPT_GENERATION_USER.format(
            persona_ctx=persona_ctx,
            outline=outline,
            duration=duration,
            word_count=word_count,
            cta_style=constraints.get("cta_style", "关注收藏"),
            taboo_words=constraints.get("taboo_words", "无"),
        )
        return await self._chat(SCRIPT_GENERATION_SYSTEM, user)

    async def polish_light(self, text: str, persona_ctx: str) -> str:
        from app.modules.content.prompts import LIGHT_POLISH_SYSTEM, LIGHT_POLISH_USER
        return await self._chat(LIGHT_POLISH_SYSTEM, LIGHT_POLISH_USER.format(persona_ctx=persona_ctx, text=text))

    async def validation_rewrite(self, script: str, persona_ctx: str, issues: str) -> str:
        from app.modules.content.prompts import VALIDATION_REWRITE_SYSTEM, VALIDATION_REWRITE_USER
        return await self._chat(
            VALIDATION_REWRITE_SYSTEM,
            VALIDATION_REWRITE_USER.format(persona_ctx=persona_ctx, script=script, issues=issues),
        )


def _parse_json(raw: str) -> dict:
    """LLM 输出解析为 JSON（容错：剥离 markdown 代码块标记）"""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    try:
        return _json.loads(text)
    except _json.JSONDecodeError:
        # 尝试提取第一个 { ... } 块
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return _json.loads(text[start:end])
            except _json.JSONDecodeError:
                pass
        return {"raw": raw}


class FFmpegCompose:
    """
    FFmpeg 子进程编排（架构借鉴 MoneyPrinterTurbo，MIT）
    合成能力：concat / overlay / subtitles(ASS) / sidechaincompress / scale+pad
    未安装 FFmpeg 时回落 Mock 产物。
    """

    name = "ffmpeg-local"

    def __init__(self) -> None:
        self._mock = MockCompose()

    async def compose(self, inp: ComposeInput) -> ComposeResult:
        # MVP：输入素材多为 mock 占位文本，直接走 mock 产物；
        # 真实视频输入时走 ffmpeg 子进程（subtitles + sidechaincompress 命令组装在此扩展）
        return await self._mock.compose(inp)


class ThirdPartyParser:
    """解析降级链：自建解析 → 第三方解析 API → 手动上传兜底（C2，100% 可用）"""

    name = "third-party-parse"

    def __init__(self) -> None:
        self._mock = MockParser()

    async def parse_url(self, url: str) -> ParseResult:
        if not settings.parse_api_url:
            return await self._mock.parse_url(url)
        # TODO(real): 第三方去水印解析 API
        raise StepRecoverableError("第三方解析尚未联调")
