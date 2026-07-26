"""Provider 运行时配置切换回归测试。"""


async def test_deepseek_rebuilds_client_when_base_url_changes(monkeypatch) -> None:
    from app.providers import real

    config = {
        "deepseek_api_key": "same-key",
        "deepseek_base_url": "https://api.deepseek.com/v1",
    }

    async def fake_get_config(key: str, default: str = "") -> str:
        return config.get(key, default)

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            self.base_url = kwargs["base_url"]
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    clients: list[FakeClient] = []

    def create_client(**kwargs) -> FakeClient:
        client = FakeClient(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(real, "get_config", fake_get_config)
    monkeypatch.setattr(real.httpx, "AsyncClient", create_client)
    provider = real.DeepSeekLLM()

    first = await provider._get_client()
    config["deepseek_base_url"] = "https://api.deepseek.com/v1/alternate"
    second = await provider._get_client()

    assert first is not second
    assert first.closed is True
    assert second.base_url == "https://api.deepseek.com/v1/alternate"


async def test_deepseek_uses_long_generation_read_timeout(monkeypatch) -> None:
    from app.providers import real

    async def fake_get_config(key: str, default: str = "") -> str:
        return {
            "deepseek_api_key": "test-key",
            "deepseek_base_url": "https://api.deepseek.com/v1",
        }.get(key, default)

    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(real, "get_config", fake_get_config)
    monkeypatch.setattr(real.httpx, "AsyncClient", FakeClient)

    await real.DeepSeekLLM()._get_client()

    timeout = captured["timeout"]
    assert isinstance(timeout, real.httpx.Timeout)
    assert timeout.read == 90.0


async def test_deepseek_retry_exhaustion_keeps_provider_error_type(monkeypatch) -> None:
    import httpx
    import pytest
    from tenacity import wait_none

    from app.providers.base import StepRecoverableError
    from app.providers.real import DeepSeekLLM

    class TimeoutClient:
        async def post(self, *args, **kwargs):
            del args, kwargs
            raise httpx.ReadTimeout("generation timed out")

    provider = DeepSeekLLM()

    async def fake_get_client() -> TimeoutClient:
        return TimeoutClient()

    async def fake_get_model() -> str:
        return "deepseek-chat"

    monkeypatch.setattr(provider, "_get_client", fake_get_client)
    monkeypatch.setattr(provider, "_get_model", fake_get_model)

    call = provider._chat.retry_with(wait=wait_none())  # type: ignore[attr-defined]
    with pytest.raises(StepRecoverableError, match="generation timed out"):
        await call(provider, "system", "user")


async def test_hifly_rebuilds_client_when_base_url_changes(monkeypatch) -> None:
    from app.providers import hifly

    config = {
        "feiying_api_key": "same-token",
        "feiying_base_url": "https://hfw-api.hifly.cc",
    }

    async def fake_get_config(key: str, default: str = "") -> str:
        return config.get(key, default)

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            self.base_url = kwargs["base_url"]
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    clients: list[FakeClient] = []

    def create_client(**kwargs) -> FakeClient:
        client = FakeClient(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(hifly, "get_config", fake_get_config)
    monkeypatch.setattr(hifly.httpx, "AsyncClient", create_client)
    provider = hifly.HiFlyClient()

    first = await provider._ensure_client()
    config["feiying_base_url"] = "https://hfw-api.hifly.cc/alternate"
    second = await provider._ensure_client()

    assert first is not second
    assert first.closed is True
    assert second.base_url == "https://hfw-api.hifly.cc/alternate"
