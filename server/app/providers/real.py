"""
真实 Provider 实现骨架
- DeepSeek（LLM 主力，OpenAI 兼容协议）
- 声音克隆 + 数字人已迁移到 hifly.py（HiFlyVoice / HiFlyAvatar）
- 生成读取超时 90s + 重试 2 次（tenacity），失败抛 StepRecoverableError 触发降级链
- 凭据从前端设置页动态读取（dynamic_config），保存即时生效无需重启
"""

import asyncio
import json as _json
import tempfile
from collections import Counter
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.core.dynamic_config import get_config
from app.core.logging import get_logger
from app.core.storage import exists, local_path, read_bytes, save_bytes

from .base import (
    ComposeInput,
    ComposeResult,
    ParseResult,
    SimilarityResult,
    StepRecoverableError,
)
from .cover import render_cover
from .media_quality import inspect_media

logger = get_logger("oral.providers.real")
settings = get_settings()
TIMEOUT = httpx.Timeout(connect=10.0, read=90.0, write=30.0, pool=10.0)


class DeepSeekLLM:
    """DeepSeek-V3 主力（openai SDK 兼容协议）；凭据从前端设置页动态读取"""

    name = "deepseek-v3"

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._client_config: tuple[str, str] | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """动态获取 HTTP 客户端（凭据变更时自动重建）"""
        api_key = await get_config("deepseek_api_key")
        base_url = await get_config("deepseek_base_url", "https://api.deepseek.com/v1")
        if not api_key:
            raise StepRecoverableError("deepseek key 未配置，请在设置页填写")
        client_config = (api_key, base_url)
        if self._client is None or self._client_config != client_config:
            if self._client:
                await self._client.aclose()
            self._client = httpx.AsyncClient(
                base_url=base_url,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=TIMEOUT,
            )
            self._client_config = client_config
        return self._client

    async def _get_model(self) -> str:
        return await get_config("deepseek_model", "deepseek-chat")

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=8), reraise=True)
    async def _chat(self, system: str, user: str, temperature: float = 0.8) -> str:
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
                    "temperature": temperature,
                },
            )
            resp.raise_for_status()
            return str(resp.json()["choices"][0]["message"]["content"])
        except httpx.HTTPError as e:
            raise StepRecoverableError(f"deepseek 调用失败: {e}") from e

    async def rewrite(self, text: str, intensity: str, prompt: str | None = None) -> str:
        level = {
            "light": "轻度润色，保持原意",
            "structure": "保留结构，语义级重写",
            "theme": "只借鉴主题，完全重新创作",
        }.get(intensity, "轻度润色")
        sys = "你是爆款口播文案专家。仿写要求：口语化、有钩子、无抄袭风险。"
        extra = f"\n额外指令：{prompt}" if prompt else ""
        return await self._chat(sys, f"请对以下文案进行{level}：\n{text}{extra}")

    async def generate_topics(self, keyword: str, count: int = 5) -> list[str]:
        raw = await self._chat("你是短视频选题策划", f"围绕「{keyword}」生成 {count} 个爆款口播选题，每行一个")
        return [line.strip(" 0123456789.、") for line in raw.splitlines() if line.strip()][:count]

    async def check_similarity(self, text: str, reference_text: str | None = None) -> SimilarityResult:
        """计算输出相对原文的 4-gram 重复率；无原文时检测文本内部重复。"""
        normalized = "".join(text.split())
        if len(normalized) < 8:
            return SimilarityResult(score=0.0)
        grams = [normalized[index : index + 4] for index in range(len(normalized) - 3)]
        if reference_text:
            reference = "".join(reference_text.split())
            reference_grams = {reference[index : index + 4] for index in range(max(0, len(reference) - 3))}
            repeated = set(grams) & reference_grams
        else:
            repeated = {gram for gram, count in Counter(grams).items() if count > 1}
        score = min(100.0, len(repeated) / max(len(set(grams)), 1) * 100)
        spans = []
        for gram in sorted(repeated)[:5]:
            start = normalized.find(gram)
            spans.append({"text": gram, "start": start, "end": start + len(gram)})
        return SimilarityResult(score=round(score, 2), duplicated_spans=spans)

    async def generate_titles(self, script: str, platform: str, count: int = 3) -> list[str]:
        raw = await self._chat(
            "你是短视频标题党（合规版）",
            f"为以下口播稿生成 {count} 组适配{platform}风格的标题+话题标签：\n{script[:400]}",
        )
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
            extra_prompt=constraints.get("extra_prompt", "") or "无",
        )
        return await self._chat(SCRIPT_GENERATION_SYSTEM, user)

    async def generate_script_variant(
        self,
        outline: str,
        persona_ctx: str,
        constraints: dict,
        temperature: float,
        strategy: str,
    ) -> str:
        duration = constraints.get("duration", 60)
        extra_prompt = constraints.get("extra_prompt", "")
        user = (
            f"人设：\n{persona_ctx or '保持自然、可信的中文口播表达'}\n\n"
            f"大纲：\n{outline}\n\n"
            f"本候选策略：{strategy}\n"
            f"目标时长：{duration} 秒\n"
            f"CTA 风格：{constraints.get('cta_style', '关注收藏')}\n"
            f"禁忌词：{constraints.get('taboo_words', '无')}\n"
            f"额外要求：{extra_prompt or '无'}"
        )
        return await self._chat(
            "你是短视频口播文案专家。请严格沿用给定大纲，但按候选策略生成一篇完整且可直接拍摄的独立文案。",
            user,
            temperature=temperature,
        )

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
        lines = [line for line in lines if not line.strip().startswith("```")]
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
    合成能力：音视频标准化、ASS 字幕、Logo/BGM、H.264/AAC 编码和封面提取。
    """

    name = "ffmpeg-local"

    async def compose(self, inp: ComposeInput) -> ComposeResult:
        if not inp.video_key:
            raise StepRecoverableError("缺少数字人或原始视频素材")
        width, height = _target_size(inp.ratio)
        with tempfile.TemporaryDirectory(prefix="oral-compose-") as directory:
            workdir = Path(directory)
            video_path = await _materialize(inp.video_key, workdir, "video")
            audio_path = await _materialize(inp.audio_key, workdir, "audio") if inp.audio_key else None
            bgm_path = await _materialize(inp.bgm_key, workdir, "bgm") if inp.bgm_key else None
            logo_path = await _materialize(inp.logo_key, workdir, "logo") if inp.logo_key else None
            subtitle_path = workdir / "subtitles.ass"
            if inp.subtitle_words:
                subtitle_path.write_text(
                    _build_ass(inp.subtitle_words, width, height, inp.subtitle_style), encoding="utf-8"
                )

            output_path = workdir / "final.mp4"
            cover_path = workdir / "cover.jpg"
            command = _compose_command(
                video_path,
                audio_path,
                bgm_path,
                logo_path,
                subtitle_path if inp.subtitle_words else None,
                output_path,
                width,
                height,
                bgm_volume=inp.bgm_volume,
            )
            await _run_ffmpeg(command, limit_seconds=300)
            await _extract_cover_frame(output_path, cover_path)
            cover_bytes = cover_path.read_bytes()
            if inp.cover_template != "none" and inp.cover_text.strip():
                # 封面自动生成（14 号方案 §3.5）：帧底图 + 模板槽位 + 标题自动排版
                try:
                    cover_bytes = await asyncio.to_thread(
                        render_cover, cover_bytes, inp.cover_text, inp.cover_template, width, height
                    )
                except Exception:
                    # 模板渲染失败不阻断成片，回退原始帧封面
                    logger.warning("cover_render_failed", exc_info=True, extra={"template": inp.cover_template})
            video_key = await save_bytes("compose", "final.mp4", output_path.read_bytes())
            cover_key = await save_bytes("compose", "cover.jpg", cover_bytes)

        report = await inspect_media(
            video_key,
            require_audio=True,
            expected_width=width,
            expected_height=height,
        )
        return ComposeResult(
            video_key=video_key,
            cover_key=cover_key,
            duration=report.duration,
            quality=report.to_dict(),
        )


class ThirdPartyParser:
    """解析降级链：自建解析 → 第三方解析 API → 手动上传兜底（C2，100% 可用）"""

    name = "third-party-parse"

    async def parse_url(self, url: str) -> ParseResult:
        if not settings.parse_api_url:
            raise StepRecoverableError("第三方解析服务未配置")
        headers = {"Authorization": f"Bearer {settings.parse_api_key}"} if settings.parse_api_key else {}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                response = await client.post(settings.parse_api_url, json={"url": url}, headers=headers)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise StepRecoverableError(f"第三方解析失败: {exc}") from exc
        data = payload.get("data", payload)
        video_url = data.get("video_url") or data.get("video") or data.get("url")
        if isinstance(video_url, list):
            video_url = video_url[0] if video_url else None
        if not isinstance(video_url, str) or not video_url.startswith(("http://", "https://")):
            raise StepRecoverableError("第三方解析未返回可访问视频地址")
        return ParseResult(
            platform=str(data.get("platform") or "other"),
            title=str(data.get("title") or ""),
            video_key=video_url,
        )


def _target_size(ratio: str) -> tuple[int, int]:
    return {
        "16:9": (1920, 1080),
        "1:1": (1080, 1080),
    }.get(ratio, (1080, 1920))


async def _materialize(key: str, directory: Path, name: str) -> Path:
    if settings.storage_driver == "local" and exists(key):
        return local_path(key)
    try:
        data = await read_bytes(key)
    except (FileNotFoundError, OSError) as exc:
        raise StepRecoverableError(f"合成素材不存在: {name}") from exc
    suffix = Path(key).suffix or ".bin"
    path = directory / f"{name}{suffix}"
    await asyncio.to_thread(path.write_bytes, data)
    return path


def _file_nonempty(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


async def _extract_cover_frame(video: Path, cover: Path) -> None:
    """封面底图：优先取 1s 处帧（口播开场站定后更稳），过短视频回退首帧"""
    try:
        await _run_ffmpeg(
            ["ffmpeg", "-y", "-ss", "1", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(cover)],
            limit_seconds=60,
        )
        if await asyncio.to_thread(_file_nonempty, cover):
            return
    except StepRecoverableError:
        pass
    await _run_ffmpeg(
        ["ffmpeg", "-y", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(cover)],
        limit_seconds=60,
    )


def _compose_command(
    video: Path,
    audio: Path | None,
    bgm: Path | None,
    logo: Path | None,
    subtitles: Path | None,
    output: Path,
    width: int,
    height: int,
    *,
    bgm_volume: float = 0.12,
) -> list[str]:
    command = ["ffmpeg", "-y", "-i", str(video)]
    audio_index = None
    bgm_index = None
    logo_index = None
    next_index = 1
    if audio:
        audio_index = next_index
        command.extend(["-i", str(audio)])
        next_index += 1
    if bgm:
        bgm_index = next_index
        command.extend(["-stream_loop", "-1", "-i", str(bgm)])
        next_index += 1
    if logo:
        logo_index = next_index
        command.extend(["-i", str(logo)])

    video_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=30"
    )
    if subtitles:
        escaped = str(subtitles).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        video_filter += f",subtitles='{escaped}'"

    filter_parts: list[str] = []
    video_map = "0:v:0"
    if logo_index is not None:
        filter_parts.extend(
            [
                f"[0:v]{video_filter}[vbase]",
                f"[{logo_index}:v]scale=180:-1[logo]",
                "[vbase][logo]overlay=W-w-40:40[vout]",
            ]
        )
        video_map = "[vout]"

    audio_map = f"{audio_index}:a:0" if audio_index is not None else "0:a:0?"
    if bgm_index is not None and audio_index is not None:
        volume = max(0.0, min(bgm_volume, 1.0))
        filter_parts.append(f"[{audio_index}:a]volume=1,asplit=2[voice][sidechain]")
        filter_parts.append(f"[{bgm_index}:a]volume={volume:g}[bgm]")
        filter_parts.append("[bgm][sidechain]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=250[ducked]")
        filter_parts.append("[voice][ducked]amix=inputs=2:duration=first:dropout_transition=2[aout]")
        audio_map = "[aout]"

    if filter_parts:
        command.extend(["-filter_complex", ";".join(filter_parts)])
        if logo_index is None:
            command.extend(["-vf", video_filter])
    else:
        command.extend(["-vf", video_filter])
    command.extend(["-map", video_map, "-map", audio_map])
    command.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "21",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-shortest",
            str(output),
        ]
    )
    return command


async def _run_ffmpeg(command: list[str], *, limit_seconds: float) -> None:
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=limit_seconds)
    except FileNotFoundError as exc:
        raise StepRecoverableError("FFmpeg 未安装或不可执行") from exc
    except TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise StepRecoverableError("FFmpeg 合成超时") from exc
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace")[-500:]
        raise StepRecoverableError(f"FFmpeg 合成失败(exit={process.returncode}): {detail}")


def _ass_color(hex_color: str) -> str:
    """#RRGGBB → ASS &H00BBGGRR（ABGR 小端序）"""
    value = (hex_color or "").lstrip("#")
    if len(value) != 6:
        return "&H00FFFFFF"
    try:
        r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "&H00FFFFFF"
    return f"&H00{b:02X}{g:02X}{r:02X}"


def _ass_style_line(width: int, height: int, style: dict | None) -> str:
    """剪辑台字幕配置 → ASS Style 行（字号按 1080 基准短边缩放，位置映射九宫格）"""
    style = style or {}
    scale = min(width, height) / 1080
    try:
        base_size = float(style.get("fontSize") or 54)
    except (TypeError, ValueError):
        base_size = 54.0
    font_size = round(max(24.0, min(120.0, base_size)) * scale)
    primary = _ass_color(str(style.get("color") or "#FFFFFF"))
    position = str(style.get("position") or "bottom")
    alignment = {"top": 8, "middle": 5}.get(position, 2)
    margin_v = {"top": round(80 * scale), "middle": 0}.get(position, round(120 * scale))
    stroke = style.get("stroke", 3)
    if isinstance(stroke, bool):
        stroke = 3 if stroke else 0
    try:
        outline = max(0, min(8, round(float(stroke))))
    except (TypeError, ValueError):
        outline = 3
    return f"Style: Default,Arial,{font_size},{primary},&H00000000,1,{outline},0,{alignment},60,60,{margin_v},1"


# 字幕分行：硬断句标点立即换行；软断句标点行长达标后换行；停顿间隙/行长上限兜底
_HARD_BREAKERS = set("。！？!?；;…")
_SOFT_BREAKERS = set("，,、：:")
_MAX_LINE_CHARS = 16
_SOFT_LINE_CHARS = 10
_PAUSE_GAP_SECONDS = 0.5


def _split_subtitle_groups(words: list) -> list[list]:
    """按语句/停顿切分字幕行：每行起止=句首字 start/句末字 end，说到哪句显示哪句"""
    groups: list[list] = []
    current: list = []
    length = 0
    for word in words:
        # 明显停顿（换气/句间留白）处先切行，停顿期字幕不滞留
        if current and word.start - current[-1].end > _PAUSE_GAP_SECONDS:
            groups.append(current)
            current, length = [], 0
        current.append(word)
        length += len(word.word.strip())
        tail = word.word.strip()[-1:]
        soft_break = tail in _SOFT_BREAKERS and length >= _SOFT_LINE_CHARS
        if tail in _HARD_BREAKERS or length >= _MAX_LINE_CHARS or soft_break:
            groups.append(current)
            current, length = [], 0
    if current:
        groups.append(current)
    return groups


def _build_ass(words: list, width: int, height: int, style: dict | None = None) -> str:
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BorderStyle, "
        "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"{_ass_style_line(width, height, style)}\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    events: list[str] = []
    for group in _split_subtitle_groups(words):
        text = "".join(word.word for word in group).replace("\n", " ").replace("{", "（").replace("}", "）")
        events.append(f"Dialogue: 0,{_ass_time(group[0].start)},{_ass_time(group[-1].end)},Default,,0,0,0,,{text}")
    return header + "\n".join(events) + "\n"


def _ass_time(seconds: float) -> str:
    total = max(0, int(seconds * 100))
    hours, remainder = divmod(total, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    secs, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"
