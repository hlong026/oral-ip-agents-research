"""Douyidou request signing must match the official Python SDK."""

import hashlib


async def test_request_uses_official_url_encoding_for_query_and_signature(monkeypatch) -> None:
    from app.providers import douyidou

    source_url = "https://www.douyin.com/jingxuan?modal_id=7623347570785471796"
    encoded_params = "app_id=demo-app&url=https%3A%2F%2Fwww.douyin.com%2Fjingxuan%3Fmodal_id%3D7623347570785471796"
    expected_sign = hashlib.md5(f"{encoded_params}demo-secret".encode()).hexdigest()
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"code": 0}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def get(self, url: str, *, headers: dict[str, str]):
            captured["url"] = url
            captured["headers"] = headers
            return FakeResponse()

    async def fake_credentials() -> tuple[str, str, str]:
        return "demo-app", "demo-secret", "https://gateway.diadi.cn"

    parser = douyidou.DouyidouParser()
    monkeypatch.setattr(parser, "_get_credentials", fake_credentials)
    monkeypatch.setattr(douyidou.httpx, "AsyncClient", lambda **_kwargs: FakeClient())

    result = await parser._request(source_url)

    assert result == {"code": 0}
    assert captured == {
        "url": f"https://gateway.diadi.cn/api/parse?{encoded_params}",
        "headers": {"Sign": expected_sign},
    }
