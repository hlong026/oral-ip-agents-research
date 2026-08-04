"""Production safety boundary for local FFmpeg composition."""

from .base import ComposeInput, ComposeResult, StepRecoverableError
from .real import FFmpegCompose, _ffmpeg_has_filter


class FailClosedFFmpegCompose(FFmpegCompose):
    """Reject subtitle renders when the runtime cannot burn the requested subtitles.

    Returning a technically valid MP4 without subtitles is a silent product failure:
    the user explicitly enabled subtitles and the publication revision is expected to
    be immutable. Subtitle-disabled jobs still delegate to the normal FFmpeg engine.
    """

    async def compose(self, inp: ComposeInput) -> ComposeResult:
        if inp.subtitle_words and not await _ffmpeg_has_filter("subtitles"):
            raise StepRecoverableError(
                "字幕渲染组件不可用，已停止生成，避免输出缺少字幕的成片；请检查 FFmpeg libass 后重试"
            )
        return await super().compose(inp)
