"""Verified URL duration must drive ASR reservation quantity."""

from contextlib import asynccontextmanager


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
