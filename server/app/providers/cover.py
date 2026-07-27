"""
封面自动生成器（14 号方案 §3.5 P0）
底图（视频帧）+ 预设模板 + 标题自动排版 + 遮罩自适应，Pillow 绘制。
- 模板 = 槽位预填值（遮罩样式 / 标题落区 / 配色）
- 标题按字数分级排版：≤8 字特大号单行、9~14 字大号单行、更长折两行降一级
- 标题落区亮度采样决定遮罩浓度，文字恒带描边，保证任意底图对比度达标
- 标题中 `【】` 标注的爆点词渲染为高亮色（与字幕关键词高亮同色系）
"""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageStat

# 模板槽位预填值；key 与前端剪辑台封面卡一致
COVER_TEMPLATES: dict[str, dict] = {
    # 大字标题：底部渐变压暗 + 下三分之一大粗体（默认）
    "bold-bottom": {"mask": "bottom", "anchor": 0.72, "accent": "#FDE047"},
    # 居中色带：品牌色半透明横带 + 居中标题
    "center-band": {"mask": "band", "anchor": 0.5, "accent": "#FFFFFF"},
    # 顶部标题：顶部渐变 + 上四分之一标题（适配底部被平台 UI 遮挡的场景）
    "top-title": {"mask": "top", "anchor": 0.16, "accent": "#FDE047"},
    # 原始首帧：不叠加任何文字层
    "none": {},
}
DEFAULT_TEMPLATE = "bold-bottom"

_HIGHLIGHT_RE = re.compile(r"【([^】]{1,12})】")

# 可商用 CJK 粗体优先；容器内走 fonts-noto-cjk，开发机走系统字体
_FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/msyh.ttc",
]


def _resolve_font_path() -> str | None:
    for candidate in _FONT_CANDIDATES:
        path = Path(candidate)
        if not path.exists():
            continue
        if _font_supports_cjk(str(path)):
            return str(path)
    return None


def _font_supports_cjk(font_path: str) -> bool:
    """字形覆盖检测（借鉴 MoneyPrinterTurbo，MIT）：缺字掩码比对，避免豆腐块"""
    try:
        font = ImageFont.truetype(font_path, 30)
        missing = font.getmask("\U0010ffff")
        sample = font.getmask("测")
        return not (missing.size == sample.size and missing.tobytes() == sample.tobytes())
    except OSError:
        return False


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = _resolve_font_path()
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def _title_lines(title: str, width: int) -> tuple[list[str], int]:
    """字数分级排版：返回（行列表, 字号）。字号以画布宽为基准。"""
    plain = _HIGHLIGHT_RE.sub(r"\1", title)
    n = len(plain)
    if n <= 8:
        return [title], round(width * 0.13)
    if n <= 14:
        return [title], round(width * 0.1)
    # 折两行：在高亮标记边界外找中点断行，避免拆散【爆点词】
    half = len(title) // 2
    cut = half
    for offset in range(min(6, half)):
        for pos in (half - offset, half + offset):
            if 0 < pos < len(title) and not _inside_highlight(title, pos):
                cut = pos
                break
        else:
            continue
        break
    return [title[:cut], title[cut:]], round(width * 0.085)


def _inside_highlight(text: str, pos: int) -> bool:
    for match in _HIGHLIGHT_RE.finditer(text):
        if match.start() < pos < match.end():
            return True
    return False


def _segments(line: str) -> list[tuple[str, bool]]:
    """拆分高亮段：[(文本, 是否爆点词)]"""
    parts: list[tuple[str, bool]] = []
    cursor = 0
    for match in _HIGHLIGHT_RE.finditer(line):
        if match.start() > cursor:
            parts.append((line[cursor : match.start()], False))
        parts.append((match.group(1), True))
        cursor = match.end()
    if cursor < len(line):
        parts.append((line[cursor:], False))
    return parts or [(line, False)]


def _region_brightness(image: Image.Image, top: float, bottom: float) -> float:
    """标题落区亮度采样（0~255），决定遮罩浓度"""
    height = image.height
    box = (0, max(0, int(height * top)), image.width, min(height, int(height * bottom)))
    region = image.crop(box).convert("L")
    return ImageStat.Stat(region).mean[0]


def _apply_mask(image: Image.Image, style: str, brightness: float) -> Image.Image:
    """遮罩自适应：亮底图加深、暗底图减淡，保证文字对比度"""
    width, height = image.size
    base_alpha = 200 if brightness > 140 else 150 if brightness > 80 else 110
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    if style == "bottom":
        start = int(height * 0.45)
        for y in range(start, height):
            alpha = int(base_alpha * (y - start) / (height - start))
            draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
    elif style == "top":
        end = int(height * 0.42)
        for y in range(end):
            alpha = int(base_alpha * (end - y) / end)
            draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
    elif style == "band":
        band_h = int(height * 0.26)
        top = int(height * 0.5 - band_h / 2)
        draw.rectangle(
            [(0, top), (width, top + band_h)],
            fill=(10, 12, 24, min(230, base_alpha + 60)),
        )
    return Image.alpha_composite(image.convert("RGBA"), overlay)


def render_cover(
    frame_bytes: bytes,
    title: str,
    template: str,
    width: int,
    height: int,
) -> bytes:
    """在视频帧上按模板叠加标题层，输出 JPEG 字节（CPU 密集，调用方走 to_thread）"""
    image = Image.open(BytesIO(frame_bytes)).convert("RGB")
    if image.size != (width, height):
        image = image.resize((width, height), Image.LANCZOS)

    spec = COVER_TEMPLATES.get(template)
    if spec is None:
        spec = COVER_TEMPLATES[DEFAULT_TEMPLATE]
    title = title.strip()
    if not spec or not title:
        buffer = BytesIO()
        image.save(buffer, "JPEG", quality=92)
        return buffer.getvalue()

    anchor = float(spec["anchor"])
    brightness = _region_brightness(image, max(0.0, anchor - 0.15), min(1.0, anchor + 0.15))
    canvas = _apply_mask(image, str(spec["mask"]), brightness)

    lines, font_size = _title_lines(title, width)
    font = _load_font(font_size)
    stroke = max(2, font_size // 18)
    draw = ImageDraw.Draw(canvas)
    line_gap = round(font_size * 0.22)
    total_h = len(lines) * font_size + (len(lines) - 1) * line_gap
    y = int(height * anchor - total_h / 2)

    for line in lines:
        segments = _segments(line)
        widths = [draw.textlength(text, font=font) for text, _ in segments]
        x = (width - sum(widths)) / 2
        for (text, highlighted), seg_w in zip(segments, widths, strict=True):
            draw.text(
                (x, y),
                text,
                font=font,
                fill=str(spec["accent"]) if highlighted else "#FFFFFF",
                stroke_width=stroke,
                stroke_fill="#0B0E1A",
            )
            x += seg_w
        y += font_size + line_gap

    buffer = BytesIO()
    canvas.convert("RGB").save(buffer, "JPEG", quality=92)
    return buffer.getvalue()
