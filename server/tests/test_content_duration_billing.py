"""Verified URL duration must drive ASR reservation quantity."""

from contextlib import asynccontextmanager
from types import SimpleNamespace


async def test_duration_probe_does_not_retry_douyidou_in_fallback(monkeypatch) -> None:
    from app.modules.content import service
    from app.providers.base import ParseResult, StepRecoverableError
    from app.providers.douyidou import DouyidouParser

    calls = {"douyidou": 0, "fallback": 0}

    async def fake_enabled(_provider_name: str) -> bool:
        return True

    async def fake_douyidou_parse(self, _url: str, is_title: int = 0):
        del self, is_title
        calls["douyidou"] += 1
        raise StepRecoverableError("套餐未开通")

    class FallbackParser:
        name = "third-party-parse"

        async def parse_url(self, _url: str) -> ParseResult:
            calls["fallback"] += 1
            return ParseResult(
                platform="douyin",
                title="",
                video_key="https://cdn.example.com/video.mp4",
            )

    async def fake_probe_duration(
        video_url: str,
        *,
        platform: str,
        known_duration: float | None,
    ) -> float:
        assert video_url == "https://cdn.example.com/video.mp4"
        assert platform == "douyin"
        assert known_duration is None
        return 42.0

    monkeypatch.setattr(service.registry, "provider_enabled", fake_enabled)
    monkeypatch.setattr(
        service.registry,
        "parse_chain",
        [DouyidouParser(), FallbackParser()],
    )
    monkeypatch.setattr(DouyidouParser, "parse_url_full", fake_douyidou_parse)
    monkeypatch.setattr(service, "probe_duration", fake_probe_duration)

    duration = await service.probe_url_duration(
        "https://www.douyin.com/video/7623347570785471796",
        required=True,
    )

    assert duration == 42.0
    assert calls == {"douyidou": 1, "fallback": 1}


async def test_url_parse_freezes_verified_duration(monkeypatch) -> None:
    from app.modules.content import router
    from app.modules.content.schemas import ParseOut

    captured: dict[str, object] = {}

    async def fake_unit(*_args, **_kwargs) -> str:
        return "per_second"

    async def fake_probe(_url: str, *, required: bool) -> float:
        assert required is True
        return 73.2

    @asynccontextmanager
    async def fake_metered(_db, _user_id, _quote_id, _module, measures):
        captured.update(measures)
        yield "operation-test"

    async def fake_parse(_db, _user_id, _url, _persona_id, duration):
        captured["parse_duration"] = duration
        return ParseOut(transcript=None, degraded=True)

    monkeypatch.setattr(router, "quote_operation_unit", fake_unit)
    monkeypatch.setattr(router, "probe_url_duration", fake_probe)
    monkeypatch.setattr(router, "metered_operation", fake_metered)
    monkeypatch.setattr(router, "parse_url", fake_parse)

    await router.api_parse(
        body=None,
        url="https://example.com/video",
        quoteId="quote-test",
        file=None,
        user_id="user-test",
        persona_id=None,
        db=None,  # type: ignore[arg-type]
    )

    assert captured == {"seconds": 74, "assets": 1, "parse_duration": 73.2}


async def test_url_parse_reuses_successful_duration_probe_result(monkeypatch) -> None:
    from app.modules.content import service
    from app.providers.base import TranscriptResult
    from app.providers.douyidou import DouyidouParser, DouyidouParseResult

    calls = 0
    asr_inputs: list[str] = []
    source_url = "https://www.douyin.com/jingxuan?modal_id=cache-once"

    async def fake_enabled(_provider_name: str) -> bool:
        return True

    async def fake_parse(self, _url: str, is_title: int = 0) -> DouyidouParseResult:
        nonlocal calls
        del self, is_title
        calls += 1
        return DouyidouParseResult(
            platform="douyin",
            title="缓存复用",
            video_url="https://cdn.example.com/video.mp4",
            text="平台发布说明，不是完整口播",
            audio=["https://cdn.example.com/original-audio.mp3"],
            duration_sec=170,
        )

    async def fake_probe_duration(
        _video_url: str,
        *,
        platform: str,
        known_duration: float | None,
    ) -> float:
        assert platform == "douyin"
        assert known_duration == 170
        return 170

    async def fake_provider_call(_step, _providers, method, media_url, *, duration_sec):
        assert method == "transcribe"
        assert duration_sec == 170
        asr_inputs.append(media_url)
        return (
            TranscriptResult(
                text="从原始音频识别出的完整口播文案",
                words=[],
                duration=170,
            ),
            "fake-asr",
        )

    async def fake_create_script(*_args, **_kwargs):
        return SimpleNamespace(id="script-from-audio")

    monkeypatch.setattr(service.registry, "provider_enabled", fake_enabled)
    monkeypatch.setattr(DouyidouParser, "parse_url_full", fake_parse)
    monkeypatch.setattr(service, "probe_duration", fake_probe_duration)
    monkeypatch.setattr(service.registry, "run_with_fallback", fake_provider_call)
    monkeypatch.setattr(service, "_create_script_with_source_version", fake_create_script)

    assert await service.probe_url_duration(source_url, required=True) == 170
    parsed = await service.parse_url(
        None,  # type: ignore[arg-type]
        "probe-cache-user",
        source_url,
        None,
        170,
    )

    assert calls == 1
    assert asr_inputs == ["https://cdn.example.com/original-audio.mp3"]
    assert parsed.transcript is not None
    assert parsed.transcript.text == "从原始音频识别出的完整口播文案"


async def test_url_parse_uses_video_when_audio_link_is_missing(monkeypatch) -> None:
    from app.modules.content import service
    from app.providers.base import TranscriptResult
    from app.providers.douyidou import DouyidouParser, DouyidouParseResult

    asr_inputs: list[str] = []

    async def fake_enabled(_provider_name: str) -> bool:
        return True

    async def fake_parse(*_args, **_kwargs) -> DouyidouParseResult:
        return DouyidouParseResult(
            platform="douyin",
            title="视频降级",
            video_url="https://cdn.example.com/fallback-video.mp4",
            text="平台发布说明",
            duration_sec=42,
        )

    async def fake_provider_call(_step, _providers, _method, media_url, *, duration_sec):
        asr_inputs.append(media_url)
        return TranscriptResult(text="视频音轨完整文案", words=[], duration=duration_sec or 0), "fake-asr"

    async def fake_create_script(*_args, **_kwargs):
        return SimpleNamespace(id="script-from-video")

    monkeypatch.setattr(service.registry, "provider_enabled", fake_enabled)
    monkeypatch.setattr(DouyidouParser, "parse_url_full", fake_parse)
    monkeypatch.setattr(service.registry, "run_with_fallback", fake_provider_call)
    monkeypatch.setattr(service, "_create_script_with_source_version", fake_create_script)

    parsed = await service.parse_url(
        None,  # type: ignore[arg-type]
        "video-fallback-user",
        "https://www.douyin.com/video/video-fallback",
        None,
        42,
    )

    assert asr_inputs == ["https://cdn.example.com/fallback-video.mp4"]
    assert parsed.transcript is not None
    assert parsed.transcript.text == "视频音轨完整文案"


async def test_url_parse_uses_platform_text_only_when_media_is_missing(monkeypatch) -> None:
    from app.modules.content import service
    from app.modules.content.schemas import ParseOut, TranscriptOut
    from app.providers.base import ParseResult
    from app.providers.douyidou import DouyidouParser, DouyidouParseResult

    async def fake_enabled(_provider_name: str) -> bool:
        return True

    async def fake_parse(*_args, **_kwargs) -> DouyidouParseResult:
        return DouyidouParseResult(
            platform="douyin",
            title="仅剩平台文本",
            text="音视频都不可用时保留的发布说明",
        )

    async def no_fallback_media(*_args, **_kwargs):
        return ParseResult(platform="douyin", title="", video_key=None), "unavailable"

    async def fake_save(_db, _user_id, _persona_id, _source_url, result) -> ParseOut:
        return ParseOut(
            transcript=TranscriptOut(text=result.text or "", words=[], duration=0),
            degraded=False,
        )

    monkeypatch.setattr(service.registry, "provider_enabled", fake_enabled)
    monkeypatch.setattr(DouyidouParser, "parse_url_full", fake_parse)
    monkeypatch.setattr(service.registry, "run_with_fallback", no_fallback_media)
    monkeypatch.setattr(service, "_save_text_result", fake_save)

    parsed = await service.parse_url(
        None,  # type: ignore[arg-type]
        "text-fallback-user",
        "https://www.douyin.com/video/text-fallback",
        None,
    )

    assert parsed.transcript is not None
    assert parsed.transcript.text == "音视频都不可用时保留的发布说明"
