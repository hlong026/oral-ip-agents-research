"""Provider 配置完整性与无副作用探测。"""


def test_douyidou_status_lists_both_missing_credentials() -> None:
    from app.modules.settings.router import _build_provider_status

    status = _build_provider_status(
        "douyidou",
        {
            "douyidou_enabled": "true",
            "douyidou_app_id": "",
            "douyidou_app_secret": "",
            "douyidou_base_url": "https://gateway.diadi.cn",
        },
    )

    assert status.configured is False
    assert status.missingFields == ["App ID", "App Secret"]
    assert status.probeMode == "sample"


async def test_deepseek_probe_verifies_model_and_masks_credentials(monkeypatch) -> None:
    from app.modules.settings import router

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": [{"id": "deepseek-chat"}]}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url: str, **kwargs):
            assert url == "https://api.deepseek.com/v1/models"
            assert kwargs["headers"]["Authorization"] == "Bearer secret-value"
            return FakeResponse()

    monkeypatch.setattr(router.httpx, "AsyncClient", lambda **_kwargs: FakeClient())

    result = await router._probe_provider(
        "deepseek",
        {
            "deepseek_api_key": "secret-value",
            "deepseek_base_url": "https://api.deepseek.com/v1",
            "deepseek_model": "deepseek-chat",
            "deepseek_enabled": "true",
        },
    )

    assert result.status == "verified"
    assert result.details == {"models": ["deepseek-chat"], "selectedModel": "deepseek-chat"}
    assert "secret-value" not in result.model_dump_json()


async def test_douyidou_probe_requires_real_sample() -> None:
    from app.modules.settings.router import _probe_provider

    result = await _probe_provider(
        "douyidou",
        {
            "douyidou_app_id": "app-id",
            "douyidou_app_secret": "app-secret",
            "douyidou_base_url": "https://gateway.diadi.cn",
            "douyidou_enabled": "true",
        },
    )

    assert result.status == "needs_sample"
    assert "样例链接" in result.message


async def test_dashscope_probe_uses_selected_region_endpoint(monkeypatch) -> None:
    from app.modules.settings import router

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url: str, **kwargs):
            assert url == "https://dashscope-intl.aliyuncs.com/api/v1/files"
            assert kwargs["params"] == {"page_no": 1, "page_size": 1}
            return FakeResponse()

    monkeypatch.setattr(router.httpx, "AsyncClient", lambda **_kwargs: FakeClient())

    result = await router._probe_provider(
        "dashscope_asr",
        {
            "dashscope_api_key": "test-key",
            "dashscope_workspace_id": "",
            "dashscope_region": "ap-southeast-1",
            "asr_model": "fun-asr",
            "asr_flash_model": "fun-asr-flash",
            "dashscope_enabled": "true",
        },
    )

    assert result.status == "verified"
    assert result.details["region"] == "ap-southeast-1"
