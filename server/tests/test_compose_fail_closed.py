"""Subtitle rendering must fail closed when FFmpeg cannot burn subtitles."""

from app.providers.base import ComposeInput, ComposeResult, StepRecoverableError, WordTs
from app.providers.compose_guard import FailClosedFFmpegCompose
from app.providers.real import FFmpegCompose


def _input(*, subtitles: bool) -> ComposeInput:
    return ComposeInput(
        video_key="video/source.mp4",
        audio_key=None,
        subtitle_words=[WordTs(word="必须显示", start=0.0, end=0.8)] if subtitles else [],
        subtitle_style={},
        bgm_key=None,
        bgm_mode="off",
        cover_text="",
    )


async def test_subtitle_request_fails_when_filter_is_unavailable(monkeypatch):
    async def unavailable(_name: str) -> bool:
        return False

    async def must_not_delegate(_self, _inp):
        raise AssertionError("缺少字幕滤镜时不得进入 FFmpeg 合成")

    monkeypatch.setattr("app.providers.compose_guard._ffmpeg_has_filter", unavailable)
    monkeypatch.setattr(FFmpegCompose, "compose", must_not_delegate)

    try:
        await FailClosedFFmpegCompose().compose(_input(subtitles=True))
    except StepRecoverableError as exc:
        assert "字幕渲染组件不可用" in str(exc)
    else:
        raise AssertionError("字幕开启且滤镜缺失时必须失败关闭")


async def test_subtitle_disabled_job_does_not_require_filter(monkeypatch):
    async def unavailable(_name: str) -> bool:
        return False

    delegated: list[ComposeInput] = []

    async def fake_compose(_self, inp: ComposeInput) -> ComposeResult:
        delegated.append(inp)
        return ComposeResult(
            video_key="compose/out.mp4",
            cover_key="compose/out.jpg",
            duration=1.0,
            quality={"passed": True},
        )

    monkeypatch.setattr("app.providers.compose_guard._ffmpeg_has_filter", unavailable)
    monkeypatch.setattr(FFmpegCompose, "compose", fake_compose)

    result = await FailClosedFFmpegCompose().compose(_input(subtitles=False))

    assert result.video_key == "compose/out.mp4"
    assert len(delegated) == 1
    assert delegated[0].subtitle_words == []


async def test_available_filter_delegates_subtitle_render(monkeypatch):
    async def available(name: str) -> bool:
        return name == "subtitles"

    delegated: list[ComposeInput] = []

    async def fake_compose(_self, inp: ComposeInput) -> ComposeResult:
        delegated.append(inp)
        return ComposeResult(
            video_key="compose/subtitled.mp4",
            cover_key="compose/cover.jpg",
            duration=1.0,
            quality={"passed": True},
        )

    monkeypatch.setattr("app.providers.compose_guard._ffmpeg_has_filter", available)
    monkeypatch.setattr(FFmpegCompose, "compose", fake_compose)

    result = await FailClosedFFmpegCompose().compose(_input(subtitles=True))

    assert result.video_key == "compose/subtitled.mp4"
    assert [word.word for word in delegated[0].subtitle_words] == ["必须显示"]
