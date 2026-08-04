"""
封面自动生成器（14 号方案 §3.5 P0）
底图（视频帧）+ 预设模板 + 标题自动排版 + 遮罩自适应，Pillow 绘制。
- 模板 = 槽位预填值（遮罩样式 / 标题落区 / 配色）
- 标题按字数分级排版，再实测像素宽自适应缩字号，双侧留安全边距杜绝截字
- 字体优先选最粗字重 face（Semibold/Bold/W6），保证封面标题冲击力
- 标题落区亮度采样决定遮罩浓度，文字恒带描边+柔和投影，任意底图对比度达标
- 标题中 `【】` 标注的爆点词渲染为高亮色（与字幕关键词高亮同色系）
"""

from __future__ import annotations

import functools
import re
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageStat

# 3x3 拉普拉斯核：卷积响应的方差越大越锐利，可挡运动模糊/失焦帧
_LAPLACIAN = ImageFilter.Kernel((3, 3), (0, 1, 0, 1, -4, 1, 0, 1, 0), scale=1)

# 模板槽位预填值；key 与前端剪辑台封面卡一致
COVER_TEMPLATES: dict[str, dict] = {
    # 大字标题：底部渐变压暗 + 下三分之一大粗体（默认）
    "bold-bottom": {"mask": "bottom", "anchor": 0.72, "accent": "#FDE047"},
    # 居中色带：品牌色半透明横带 + 居中标题
    "center-band": {"mask": "band", "anchor": 0.5, "accent": "#FDE047"},
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


# 字重候选按优先级降序；“bold”能同时命中 Semibold/Bold，排在 black/heavy 之后
_BOLD_HINTS = ("black", "heavy", "bold", "w7", "w6", "medium")


@functools.lru_cache(maxsize=1)
def _resolve_font_face() -> tuple[str, int] | None:
    """跨候选字体文件选最粗字重 face（ttc 默认 index 0 往往是 Regular 细体）"""
    best: tuple[str, int] | None = None
    best_rank = len(_BOLD_HINTS) + 1
    for candidate in _FONT_CANDIDATES:
        path = Path(candidate)
        if not path.exists() or not _font_supports_cjk(str(path)):
            continue
        if best is None:
            best = (str(path), 0)  # 兼容候选里没命中任何字重关键词的情况
        for index in range(32):
            try:
                face = ImageFont.truetype(str(path), 24, index=index)
            except OSError:
                break
            name = " ".join(part for part in face.getname() if part).lower()
            if name.startswith("."):
                continue  # 跳过系统隐藏 Interface 字体
            for rank, hint in enumerate(_BOLD_HINTS):
                if hint in name:
                    if rank < best_rank:
                        best_rank, best = rank, (str(path), index)
                    break
        if best_rank == 0:
            break  # 已命中最粗级，无需继续扫
    return best


def _font_supports_cjk(font_path: str) -> bool:
    """字形覆盖检测（借鉴 MoneyPrinterTurbo，MIT）：缺字掩码比对，避免豆腐块。"""
    try:
        font = ImageFont.truetype(font_path, 30)
        missing = font.getmask("\U0010ffff")
        sample = font.getmask("测")
        # Pillow 11+ 的 ImagingCore 不再暴露 tobytes()，但仍实现 buffer 协议。
        return not (missing.size == sample.size and bytes(missing) == bytes(sample))
    except (OSError, TypeError):
        return False


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    face = _resolve_font_face()
    if face:
        return ImageFont.truetype(face[0], size, index=face[1])
    return ImageFont.load_default(size)


def _title_lines(title: str, width: int) -> tuple[list[str], int]:
    """字数分级排版：返回（行列表, 基准字号）。字号以画布宽为基准，后续再按实测像素宽缩到适配。"""
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


def _fit_font(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    base_size: int,
    max_width: float,
) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, int]:
    """实测最宽行像素宽，逐步缩字号直到放得下；杜绝截字，并保留下限免得小到看不清。"""
    size = base_size
    floor = max(28, round(max_width * 0.06))
    while True:
        font = _load_font(size)
        widest = max(draw.textlength(_HIGHLIGHT_RE.sub(r"\1", line), font=font) for line in lines)
        if widest <= max_width or size <= floor:
            return font, size
        size = max(floor, int(size * 0.94))


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


def score_frame_quality(jpeg_bytes: bytes) -> float:
    """候选帧质量打分（纯 Pillow，无额外依赖）。

    清晰度（拉普拉斯方差）为主，叠加亮度惩罚：过暗/过曝按偏离舒适区衰减。
    分数越高越适合当封面；用于在锚点邻域多帧中择优，规避糊帧/欠曝帧。
    """
    gray = Image.open(BytesIO(jpeg_bytes)).convert("L")
    gray.thumbnail((640, 640), Image.Resampling.BILINEAR)  # 降采样提速并抑制噪点
    sharpness = ImageStat.Stat(gray.filter(_LAPLACIAN)).stddev[0] ** 2
    mean = ImageStat.Stat(gray).mean[0]
    if mean < 70:
        penalty = max(0.4, mean / 70)
    elif mean > 190:
        penalty = max(0.4, (255 - mean) / 65)
    else:
        penalty = 1.0
    return sharpness * penalty


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
        image = image.resize((width, height), Image.Resampling.LANCZOS)

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

    draw = ImageDraw.Draw(canvas)
    lines, base_size = _title_lines(title, width)
    # 双侧各留 6% 安全边距，实测像素宽自适应缩字号，杜绝截字
    max_text_width = width * 0.88
    font, font_size = _fit_font(draw, lines, base_size, max_text_width)
    stroke = max(2, font_size // 16)

    # 真实行高：用字体度量而非字号，避免行间叠压/基线偏移
    if isinstance(font, ImageFont.FreeTypeFont):
        ascent, descent = font.getmetrics()
        line_height = ascent + descent
    else:
        line_height = round(font_size * 1.3)
    line_gap = round(font_size * 0.14)
    total_h = len(lines) * line_height + (len(lines) - 1) * line_gap
    y = int(height * anchor - total_h / 2)
    # 垂直钳制：标题整体不超出画布上下 3% 安全区
    margin_v = int(height * 0.03)
    y = max(margin_v, min(y, height - margin_v - total_h))

    # 柔和投影层：标题整体先画在透明层上高斯模糊，再叠回画布，压得住花底图
    shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)
    offset = max(2, font_size // 24)
    sy = y
    for line in lines:
        segments = _segments(line)
        widths = [draw.textlength(text, font=font) for text, _ in segments]
        x = (width - sum(widths)) / 2
        shadow_draw.text(
            (x + offset, sy + offset),
            "".join(text for text, _ in segments),
            font=font,
            fill=(0, 0, 0, 190),
            stroke_width=stroke,
            stroke_fill=(0, 0, 0, 190),
        )
        sy += line_height + line_gap
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(max(3, font_size // 14)))
    canvas = Image.alpha_composite(canvas, shadow_layer)
    draw = ImageDraw.Draw(canvas)

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
        y += line_height + line_gap

    buffer = BytesIO()
    canvas.convert("RGB").save(buffer, "JPEG", quality=92)
    return buffer.getvalue()
