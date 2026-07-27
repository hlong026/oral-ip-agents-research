"""字幕精准同步单测：脚本×ASR 字符对齐 + 语句分行"""

from app.providers.align import MIN_MATCH_RATIO, align_script_to_asr
from app.providers.base import WordTs
from app.providers.real import _build_ass, _split_subtitle_groups


def _w(word: str, start: float, end: float) -> WordTs:
    return WordTs(word=word, start=start, end=end)


# ---------- 脚本 × ASR 对齐 ----------


def test_align_perfect_match_inherits_asr_timestamps():
    asr = [_w("今", 0.0, 0.3), _w("天", 0.3, 0.9), _w("好", 1.5, 2.0)]
    aligned = align_script_to_asr("今天好", asr)
    assert [w.word for w in aligned] == ["今", "天", "好"]
    assert aligned[0].start == 0.0 and aligned[0].end == 0.3
    assert aligned[1].end == 0.9
    # 停顿被保留：真实语音 0.9~1.5 的间隙不被抹平
    assert aligned[2].start == 1.5 and aligned[2].end == 2.0


def test_align_keeps_script_text_on_asr_typo():
    # ASR 把「账」识别成「帐」：字幕文本仍是脚本原文，时间戳在前后锚点间内插
    asr = [_w("查", 0.0, 0.4), _w("帐", 0.4, 0.8), _w("户", 0.8, 1.2)]
    aligned = align_script_to_asr("查账户", asr)
    assert "".join(w.word for w in aligned) == "查账户"
    assert aligned[0].end == 0.4
    assert aligned[2].start == 0.8
    # 错字「账」内插在锚点之间且时间轴单调
    assert 0.4 <= aligned[1].start <= aligned[1].end <= 0.8


def test_align_splits_multichar_asr_words():
    # 阿里云 ASR 返回词粒度（含标点后缀），需拆到字符粒度
    asr = [_w("你好，", 0.0, 0.6), _w("世界。", 1.0, 1.6)]
    aligned = align_script_to_asr("你好，世界。", asr)
    assert "".join(w.word for w in aligned) == "你好，世界。"
    assert aligned[0].start == 0.0
    assert aligned[3].start == 1.0  # 「世」从第二个词的真实开始时间起


def test_align_low_match_returns_empty():
    asr = [_w("完", 0.0, 0.3), _w("全", 0.3, 0.6), _w("无", 0.6, 0.9), _w("关", 0.9, 1.2)]
    assert align_script_to_asr("今天讲三个省钱技巧", asr) == []
    assert MIN_MATCH_RATIO == 0.6


def test_align_empty_inputs_return_empty():
    assert align_script_to_asr("", [_w("字", 0, 1)]) == []
    assert align_script_to_asr("有脚本", []) == []


def test_align_timeline_monotonic_with_missing_tail():
    # 脚本比识别结果长（尾部漏识别）：尾段按平均字长顺延且不回退
    asr = [_w("三", 0.0, 0.3), _w("个", 0.3, 0.6), _w("技", 0.6, 0.9), _w("巧", 0.9, 1.2)]
    aligned = align_script_to_asr("三个技巧哦", asr)
    assert "".join(w.word for w in aligned) == "三个技巧哦"
    cursor = 0.0
    for w in aligned:
        assert w.start >= cursor and w.end >= w.start
        cursor = w.end
    assert aligned[-1].start >= 1.2  # 尾字在最后锚点之后顺延


# ---------- 语句分行 ----------


def test_split_on_hard_punctuation():
    words = [_w(ch, i * 0.2, (i + 1) * 0.2) for i, ch in enumerate("今天好。明天见！")]
    groups = _split_subtitle_groups(words)
    assert ["".join(w.word for w in g) for g in groups] == ["今天好。", "明天见！"]


def test_split_on_pause_gap():
    # 无标点但有 >0.5s 停顿 → 停顿处切行，停顿期无字幕滞留
    words = [_w("先", 0.0, 0.2), _w("说", 0.2, 0.4), _w("这", 1.2, 1.4), _w("个", 1.4, 1.6)]
    groups = _split_subtitle_groups(words)
    assert len(groups) == 2
    assert groups[0][-1].end == 0.4 and groups[1][0].start == 1.2


def test_split_soft_punctuation_after_threshold():
    # 软标点（逗号）在行长≥10时切行，行长不足时不切
    text = "这里是十个字的内容哦，后面继续说"
    words = [_w(ch, i * 0.2, (i + 1) * 0.2) for i, ch in enumerate(text)]
    groups = _split_subtitle_groups(words)
    assert "".join(w.word for w in groups[0]) == "这里是十个字的内容哦，"
    short = [_w(ch, i * 0.2, (i + 1) * 0.2) for i, ch in enumerate("短句，不切行")]
    assert len(_split_subtitle_groups(short)) == 1


def test_split_hard_cap_on_long_run():
    words = [_w("字", i * 0.2, (i + 1) * 0.2) for i in range(40)]
    groups = _split_subtitle_groups(words)
    assert all(len(g) <= 16 for g in groups)
    assert sum(len(g) for g in groups) == 40


def test_build_ass_dialogue_follows_sentences():
    words = [_w(ch, i * 0.5, (i + 1) * 0.5) for i, ch in enumerate("你好。再见")]
    content = _build_ass(words, 1080, 1920)
    lines = [line for line in content.splitlines() if line.startswith("Dialogue:")]
    assert len(lines) == 2
    assert lines[0].endswith("你好。") and "0:00:00.00" in lines[0]
    # 第二句从「再」的真实时间开始
    assert lines[1].endswith("再见") and "0:00:01.50" in lines[1]


# ---------- ASR 取址三级策略 ----------


async def test_asr_media_input_embeds_data_uri_when_no_public_url(monkeypatch):
    # 未配 MEDIA_PUBLIC_BASE_URL（回退 127.0.0.1）时，短音频应内嵌为 data URI 直通 Flash 转写
    from app.core import storage
    from app.modules.pipeline.engine import _asr_media_input

    monkeypatch.setattr(storage.settings, "media_public_base_url", "")
    key = await storage.save_bytes("tts", "audio.mp3", b"fake-mp3-bytes")
    media_input = await _asr_media_input(key, 60.0)
    assert media_input.startswith("data:audio/mpeg;base64,")


async def test_asr_media_input_prefers_public_url(monkeypatch):
    from app.core import storage
    from app.modules.pipeline.engine import _asr_media_input

    monkeypatch.setattr(storage.settings, "media_public_base_url", "https://api.example.com")
    key = await storage.save_bytes("tts", "audio.mp3", b"fake-mp3-bytes")
    media_input = await _asr_media_input(key, 60.0)
    assert media_input == f"https://api.example.com/media/{key}"


async def test_asr_media_input_gives_up_on_long_audio_without_public_url(monkeypatch):
    # 长音频只能走异步转写（需公网回源），无公网地址时返回空 → 调用方回退平摊时间戳
    from app.core import storage
    from app.modules.pipeline.engine import _asr_media_input

    monkeypatch.setattr(storage.settings, "media_public_base_url", "")
    key = await storage.save_bytes("tts", "audio.mp3", b"fake-mp3-bytes")
    assert await _asr_media_input(key, 3600.0) == ""
