"""
字幕精准同步：脚本 × ASR 识别结果的字符级对齐（纯函数）
背景：TTS 供应商不返回真实字级时间戳（hifly 按总时长均匀平摊），字幕会随停顿/语速漂移。
做法：对最终 TTS 音频做 ASR 字级识别拿真实语音时间，再对齐回已知脚本——
- 匹配字符直接继承 ASR 时间戳（字幕文本 100% 等于脚本，识别错字不影响显示）
- 未匹配字符在前后锚点之间线性内插
- 整体匹配率过低（音频与脚本对不上）返回空列表，调用方回退均匀平摊时间戳
"""

from __future__ import annotations

from difflib import SequenceMatcher

from .base import WordTs

# 匹配率低于该阈值视为对齐失败（正常同文本识别应 >0.9，留容错空间给口音/错字）
MIN_MATCH_RATIO = 0.6
# 无任何锚点参照时的兜底单字时长（与 hifly/mock 平摊值一致）
_FALLBACK_CHAR_SECONDS = 0.28


def _flatten_asr_chars(asr_words: list[WordTs]) -> list[tuple[str, float, float]]:
    """ASR 词粒度 → 字符粒度：词内各字符按词时长线性切片，跳过空白"""
    chars: list[tuple[str, float, float]] = []
    for word in asr_words:
        visible = [ch for ch in word.word if ch.strip()]
        if not visible:
            continue
        span = max(0.0, word.end - word.start)
        per = span / len(visible)
        for i, ch in enumerate(visible):
            chars.append((ch, word.start + i * per, word.start + (i + 1) * per))
    return chars


def align_script_to_asr(script: str, asr_words: list[WordTs]) -> list[WordTs]:
    """把 ASR 真实时间戳对齐到脚本字符上；对齐失败返回 []（调用方回退）"""
    script_chars = [ch for ch in script if ch.strip()]
    asr_chars = _flatten_asr_chars(asr_words)
    if not script_chars or not asr_chars:
        return []

    matcher = SequenceMatcher(None, script_chars, [c[0] for c in asr_chars], autojunk=False)
    anchors: dict[int, tuple[float, float]] = {}
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            _, start, end = asr_chars[block.b + offset]
            anchors[block.a + offset] = (start, end)

    if len(anchors) / len(script_chars) < MIN_MATCH_RATIO:
        return []

    times = _interpolate(len(script_chars), anchors)
    words = [
        WordTs(word=ch, start=round(s, 3), end=round(e, 3))
        for ch, (s, e) in zip(script_chars, times, strict=True)
    ]
    return _enforce_monotonic(words)


def _interpolate(total: int, anchors: dict[int, tuple[float, float]]) -> list[tuple[float, float]]:
    """未匹配字符在前后锚点间线性内插；首尾按平均字长外推"""
    matched = sorted(anchors)
    durations = [anchors[p][1] - anchors[p][0] for p in matched]
    avg = sum(durations) / len(durations) if durations else _FALLBACK_CHAR_SECONDS
    avg = max(0.05, avg)

    times: list[tuple[float, float] | None] = [anchors.get(i) for i in range(total)]

    # 首段：第一个锚点之前，向前外推（不早于 0）
    first = matched[0]
    cursor = max(0.0, anchors[first][0] - first * avg)
    for i in range(first):
        times[i] = (cursor, cursor + avg)
        cursor += avg

    # 中段：相邻锚点之间的空隙均分
    for left, right in zip(matched, matched[1:], strict=False):
        count = right - left - 1
        if count <= 0:
            continue
        gap_start = anchors[left][1]
        per = max(0.0, anchors[right][0] - gap_start) / count
        for k in range(count):
            times[left + 1 + k] = (gap_start + k * per, gap_start + (k + 1) * per)

    # 尾段：最后一个锚点之后，按平均字长顺延
    last = matched[-1]
    cursor = anchors[last][1]
    for i in range(last + 1, total):
        times[i] = (cursor, cursor + avg)
        cursor += avg

    return [t if t is not None else (0.0, avg) for t in times]


def _enforce_monotonic(words: list[WordTs]) -> list[WordTs]:
    """保证时间轴单调不回退（浮点误差/零宽内插的兜底）"""
    cursor = 0.0
    result: list[WordTs] = []
    for word in words:
        start = max(word.start, cursor)
        end = max(word.end, start)
        result.append(WordTs(word=word.word, start=round(start, 3), end=round(end, 3)))
        cursor = end
    return result
