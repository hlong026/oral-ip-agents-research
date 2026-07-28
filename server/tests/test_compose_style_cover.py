"""字幕样式真链路 + 封面自动生成（14 号方案 §3.5 P0）单测"""

from io import BytesIO
from types import SimpleNamespace

from PIL import Image

from app.modules.pipeline.engine import _cover_text_from_ctx, _subtitle_style_from_ctx
from app.providers.base import WordTs
from app.providers.cover import _segments, _title_lines, render_cover
from app.providers.real import _ass_color, _ass_style_line, _build_ass

# ---------- ASS 字幕样式映射 ----------


def test_ass_color_maps_rgb_to_abgr():
    assert _ass_color("#FFFFFF") == "&H00FFFFFF"
    assert _ass_color("#FDE047") == "&H0047E0FD"
    assert _ass_color("#22D3EE") == "&H00EED322"


def test_ass_color_falls_back_on_bad_input():
    assert _ass_color("") == "&H00FFFFFF"
    assert _ass_color("red") == "&H00FFFFFF"
    assert _ass_color("#GGGGGG") == "&H00FFFFFF"


def test_ass_style_consumes_editor_config():
    line = _ass_style_line(1080, 1920, {"fontSize": 44, "color": "#FDE047", "position": "top", "stroke": 4})
    assert ",44," in line  # 1080 短边 → scale=1，字号原样
    assert "&H0047E0FD" in line
    fields = line.removeprefix("Style: ").split(",")
    assert fields[6] == "4"  # Outline=描边
    assert fields[8] == "8"  # top → Alignment 8
    assert fields[11] == "80"  # top MarginV


def test_ass_style_defaults_and_legacy_bool_stroke():
    # 无配置 → 与旧行为一致的默认值
    default = _ass_style_line(1080, 1920, None)
    assert ",54,&H00FFFFFF," in default
    fields = default.removeprefix("Style: ").split(",")
    assert fields[8] == "2" and fields[11] == "120"
    # 旧数据 stroke 为 bool 时容错
    legacy = _ass_style_line(1080, 1920, {"stroke": True})
    assert legacy.removeprefix("Style: ").split(",")[6] == "3"
    legacy_off = _ass_style_line(1080, 1920, {"stroke": False})
    assert legacy_off.removeprefix("Style: ").split(",")[6] == "0"


def test_ass_style_scales_by_short_edge():
    # 16:9（1920x1080）与 9:16（1080x1920）短边一致 → 同字号
    portrait = _ass_style_line(1080, 1920, {"fontSize": 44})
    landscape = _ass_style_line(1920, 1080, {"fontSize": 44})
    assert portrait.split(",")[2] == landscape.split(",")[2] == "44"


def test_build_ass_embeds_style_line():
    words = [WordTs(word="你好", start=0.0, end=0.5), WordTs(word="世界", start=0.5, end=1.0)]
    content = _build_ass(words, 1080, 1920, {"fontSize": 60, "color": "#F87171", "position": "middle", "stroke": 0})
    assert "Style: Default,Arial,60,&H007171F8,&H00000000,1,0,0,5,60,60,0,1" in content
    assert "Dialogue:" in content and "你好世界" in content


# ---------- 封面标题排版 ----------


def test_title_lines_tiered_by_length():
    lines, size_l = _title_lines("短标题", 1080)
    assert lines == ["短标题"] and size_l == round(1080 * 0.13)
    lines, size_m = _title_lines("九个字的中等标题呀", 1080)
    assert len(lines) == 1 and size_m == round(1080 * 0.1)
    lines, size_s = _title_lines("超过十四个字的超长标题会自动折成两行", 1080)
    assert len(lines) == 2 and size_s == round(1080 * 0.085)


def test_title_wrap_keeps_highlight_intact():
    title = "别乱花钱了这才是【存钱】的正确姿势"
    lines, _ = _title_lines(title, 1080)
    assert len(lines) == 2
    # 断行点不落在【存钱】内部：高亮标记要么整段在某一行
    joined = [line for line in lines if "【存钱】" in line]
    assert len(joined) == 1


def test_segments_split_highlight():
    assert _segments("警惕【隐形消费】陷阱") == [("警惕", False), ("隐形消费", True), ("陷阱", False)]
    assert _segments("无高亮") == [("无高亮", False)]


# ---------- 封面渲染 ----------


def _frame_bytes(color: str = "#888888", size: tuple[int, int] = (108, 192)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, "JPEG")
    return buffer.getvalue()


def test_render_cover_outputs_target_size_jpeg():
    data = render_cover(_frame_bytes(), "别乱花钱了【存钱】攻略", "bold-bottom", 540, 960)
    image = Image.open(BytesIO(data))
    assert image.format == "JPEG"
    assert image.size == (540, 960)


def test_render_cover_none_template_returns_plain_frame():
    plain = render_cover(_frame_bytes(), "任意标题", "none", 540, 960)
    templated = render_cover(_frame_bytes(), "任意标题", "bold-bottom", 540, 960)
    # none 模板不叠加文字层，与叠加后的结果必然不同
    assert plain != templated
    assert Image.open(BytesIO(plain)).size == (540, 960)


def test_render_cover_unknown_template_falls_back_to_default():
    data = render_cover(_frame_bytes(), "标题", "no-such-template", 540, 960)
    assert Image.open(BytesIO(data)).size == (540, 960)


def test_render_cover_empty_title_returns_frame():
    data = render_cover(_frame_bytes(), "   ", "bold-bottom", 540, 960)
    assert Image.open(BytesIO(data)).size == (540, 960)


# ---------- engine ctx 配置解析 ----------


def test_subtitle_style_parses_editor_json():
    ctx = {"subtitle_style": '{"fontSize": 50, "color": "#22D3EE", "position": "top", "stroke": 2}'}
    style = _subtitle_style_from_ctx(ctx)
    assert style == {"fontSize": 50, "color": "#22D3EE", "position": "top", "stroke": 2}


def test_subtitle_style_default_on_missing_or_bad_json():
    default = {"fontSize": 44, "color": "#FFFFFF", "position": "bottom", "stroke": 3}
    assert _subtitle_style_from_ctx({}) == default
    assert _subtitle_style_from_ctx({"subtitle_style": "not-json"}) == default


def test_cover_text_priority():
    task = SimpleNamespace(title="未命名任务")
    assert _cover_text_from_ctx(task, {"cover_title": "封面标题", "title": "普通标题"}) == "封面标题"
    assert _cover_text_from_ctx(task, {"title": "普通标题"}) == "普通标题"
    # task.title 为占位名时跳过，兜底文案截断
    assert _cover_text_from_ctx(task, {"script": "口播文案" * 10}) == ("口播文案" * 10)[:18]
    task_named = SimpleNamespace(title="真实任务标题")
    assert _cover_text_from_ctx(task_named, {}) == "真实任务标题"


def test_publish_title_not_clipped_by_cover_budget():
    from app.modules.pipeline.engine import _preferred_title

    # 发布标题取值不截断，由调用方按 30 字预算截断，不受封面 24/18 字限制
    task = SimpleNamespace(title="未命名任务")
    long_title = "标" * 28
    assert _preferred_title(task, {"cover_title": long_title}) == long_title
    # 无任何标题候选时返回空串，由调用方兜底口播文案
    assert _preferred_title(task, {}) == ""


# ---------- 字幕开关（关闭时跳过 ASS 烧录） ----------


async def _capture_compose_input(monkeypatch, ctx: dict):
    from app.modules.pipeline import engine
    from app.providers.base import ComposeResult

    captured = {}

    async def fake_run(_module, _chain, _step, inp, **_kwargs):
        captured["inp"] = inp
        result = ComposeResult(
            video_key="compose/out.mp4", cover_key="compose/out.jpg", duration=1.0, quality={"passed": True}
        )
        return result, "ffmpeg-local"

    monkeypatch.setattr(engine.registry, "run_with_fallback", fake_run)
    task = SimpleNamespace(title="开关测试", randomize=False, trace_id="trace-sub", id="task-sub")
    await engine._compose_with_ctx(task, ctx)
    return captured["inp"]


async def test_compose_skips_subtitle_words_when_disabled(monkeypatch):
    ctx = {
        "avatar_video_key": "avatar/a.mp4",
        "audio_key": "tts/a.mp3",
        "tts_words": [{"word": "你好", "start": 0.0, "end": 0.4}],
        "subtitle_enabled": False,
    }
    inp = await _capture_compose_input(monkeypatch, ctx)
    assert inp.subtitle_words == []


async def test_compose_keeps_subtitle_words_by_default(monkeypatch):
    # 未显式关闭（含存量任务无 subtitle_enabled 字段）时维持烧录行为
    ctx = {
        "avatar_video_key": "avatar/a.mp4",
        "audio_key": "tts/a.mp3",
        "tts_words": [{"word": "你好", "start": 0.0, "end": 0.4}],
    }
    inp = await _capture_compose_input(monkeypatch, ctx)
    assert [w.word for w in inp.subtitle_words] == ["你好"]
    inp_on = await _capture_compose_input(monkeypatch, {**ctx, "subtitle_enabled": True})
    assert [w.word for w in inp_on.subtitle_words] == ["你好"]
