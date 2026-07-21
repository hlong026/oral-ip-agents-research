"""Verified URL duration must drive ASR reservation quantity."""

from contextlib import asynccontextmanager


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
