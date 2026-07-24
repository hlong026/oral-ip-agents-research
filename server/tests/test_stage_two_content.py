"""第二阶段内容输入与文案资产回归测试。"""

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.core.db import SessionLocal, init_models
from app.modules.content import repository as content_repo


@pytest_asyncio.fixture(autouse=True)
async def _database() -> None:
    await init_models()


async def test_pasted_text_is_saved_without_calling_parse_provider(monkeypatch) -> None:
    from app.modules.content import service

    async def forbidden_provider_call(*_args, **_kwargs):
        raise AssertionError("正文粘贴不应调用解析或 ASR Provider")

    monkeypatch.setattr(service.registry, "run_with_fallback", forbidden_provider_call)

    async with SessionLocal() as db:
        result = await service.parse_text(db, "stage2-user", "这是直接粘贴的口播正文", None)

    assert result.degraded is False
    assert result.inputType == "text"
    assert result.sourceStatus == "ready"
    assert result.transcript is not None
    assert result.transcript.text == "这是直接粘贴的口播正文"
    assert result.scriptId


async def test_unavailable_link_returns_actionable_fallback(monkeypatch) -> None:
    from app.modules.content import service
    from app.providers.base import ParseResult

    async def disabled(_provider_name: str) -> bool:
        return False

    async def no_media(*_args, **_kwargs):
        return ParseResult(platform="douyin", title="", video_key=None), "unavailable"

    monkeypatch.setattr(service.registry, "provider_enabled", disabled)
    monkeypatch.setattr(service.registry, "run_with_fallback", no_media)

    async with SessionLocal() as db:
        try:
            await service.parse_url(db, "stage2-user", "https://www.douyin.com/video/123", None)
        except HTTPException as exc:
            assert exc.status_code == 422
            assert exc.detail["code"] == "LINK_SOURCE_UNAVAILABLE"
            assert exc.detail["fallbacks"] == ["paste_text", "upload_file"]
        else:
            raise AssertionError("不可访问链接必须返回可操作的降级提示")


async def test_manual_edit_appends_traceable_script_version() -> None:
    from app.modules.content import service

    async with SessionLocal() as db:
        created = await service.create_script(
            db,
            "stage2-version-user",
            None,
            "测试文案",
            "初始正文",
            "manual",
            None,
        )
        updated = await service.update_script(
            db,
            "stage2-version-user",
            created.id,
            title="测试文案第二版",
            text="人工修改后的正文",
        )
        versions = await service.list_script_versions(db, "stage2-version-user", created.id)

    assert updated.rewrittenText == "人工修改后的正文"
    assert updated.currentVersion == 2
    assert [version.kind for version in versions] == ["source", "manual_edit"]
    assert versions[-1].text == "人工修改后的正文"
    assert versions[-1].modelName == "human"
    assert versions[-1].promptVersion == "manual"


async def test_script_versions_are_isolated_by_user() -> None:
    from app.modules.content import service

    async with SessionLocal() as db:
        created = await service.create_script(
            db,
            "stage2-owner",
            None,
            "归属测试",
            "仅归属用户可见",
            "manual",
            None,
        )
        assert await content_repo.get(db, created.id, "stage2-owner") is not None
        try:
            await service.list_script_versions(db, "stage2-other", created.id)
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("其他用户不应读取文案版本")


async def test_asr_routes_by_verified_duration(monkeypatch) -> None:
    from app.providers.aliyun_asr import AliyunASR
    from app.providers.base import TranscriptResult

    provider = AliyunASR()
    calls: list[str] = []

    async def fake_config():
        return {
            "api_key": "test",
            "base_url": "https://example.invalid",
            "asr_model": "async",
            "flash_model": "flash",
            "threshold": 300,
            "poll_interval": 0.01,
            "poll_max_attempts": 2,
        }

    async def flash(_file_url: str, _config: dict):
        calls.append("flash")
        return TranscriptResult(text="短音频", words=[], duration=120)

    async def async_mode(_file_url: str, _config: dict):
        calls.append("async")
        return TranscriptResult(text="长音频", words=[], duration=600)

    monkeypatch.setattr(provider, "_get_config", fake_config)
    monkeypatch.setattr(provider, "_transcribe_flash", flash)
    monkeypatch.setattr(provider, "_transcribe_async", async_mode)

    assert (await provider.transcribe("short.mp4", 120)).text == "短音频"
    assert (await provider.transcribe("long.mp4", 600)).text == "长音频"
    assert calls == ["flash", "async"]


async def test_asr_poll_limits_come_from_runtime_config(monkeypatch) -> None:
    from app.providers import aliyun_asr

    async def fake_get_config(key: str, default: str = "") -> str:
        values = {
            "dashscope_api_key": "test-key",
            "asr_poll_interval": "0.25",
        }
        return values.get(key, default)

    async def fake_get_config_int(key: str, default: int = 0) -> int:
        return 7 if key == "asr_poll_max_attempts" else default

    async def fake_get_config_float(key: str, default: float = 0.0) -> float:
        return 0.25 if key == "asr_poll_interval" else default

    monkeypatch.setattr(aliyun_asr, "get_config", fake_get_config)
    monkeypatch.setattr(aliyun_asr, "get_config_int", fake_get_config_int)
    monkeypatch.setattr(aliyun_asr, "get_config_float", fake_get_config_float, raising=False)

    config = await aliyun_asr.AliyunASR()._get_config()

    assert config["poll_interval"] == 0.25
    assert config["poll_max_attempts"] == 7


async def test_production_provider_chains_never_include_mock(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.providers import registry as registry_module

    production = SimpleNamespace(app_env="prod", im_enabled=False, douyin_im_app_key="")
    monkeypatch.setattr(registry_module, "get_settings", lambda: production)

    production_registry = registry_module.ProviderRegistry()

    chains = [
        production_registry.llm_chain,
        production_registry.parse_chain,
        production_registry.asr_chain,
        production_registry.voice_chain,
        production_registry.avatar_chain,
        production_registry.compose_chain,
    ]
    assert all(not provider.name.startswith("mock") for chain in chains for provider in chain)
    assert not hasattr(production_registry, "_publish_mock_fallback")


async def test_acceptance_mode_removes_mock_provider_fallback(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.providers import registry as registry_module

    acceptance = SimpleNamespace(
        app_env="dev",
        provider_mock_fallback_enabled=False,
        im_enabled=False,
        douyin_im_app_key="",
    )
    monkeypatch.setattr(registry_module, "get_settings", lambda: acceptance)

    acceptance_registry = registry_module.ProviderRegistry()

    chains = [
        acceptance_registry.llm_chain,
        acceptance_registry.parse_chain,
        acceptance_registry.asr_chain,
        acceptance_registry.voice_chain,
        acceptance_registry.avatar_chain,
        acceptance_registry.compose_chain,
    ]
    assert all(not provider.name.startswith("mock") for chain in chains for provider in chain)


async def test_development_provider_switch_disables_real_provider(monkeypatch) -> None:
    from app.core import dynamic_config
    from app.providers.registry import ProviderRegistry

    async def disabled_config(_key: str, _default: str = "") -> str:
        return "false"

    monkeypatch.setattr(dynamic_config, "get_config", disabled_config)
    provider_registry = ProviderRegistry()

    assert await provider_registry.provider_enabled("deepseek-v3") is False
    assert await provider_registry.provider_enabled("mock-llm") is True


async def test_upload_passes_accessible_url_to_asr(monkeypatch) -> None:
    from app.modules.content import service
    from app.providers.base import TranscriptResult

    captured_urls: list[str] = []

    async def stored(_prefix: str, _filename: str, _data: bytes) -> str:
        return "uploads/source video.mp4"

    async def accessible(key: str, *, require_public: bool = False) -> str:
        assert key == "uploads/source video.mp4"
        assert require_public is False
        return "https://media.example.test/media/uploads/source%20video.mp4"

    async def transcribed(_kind: str, _chain, _method: str, file_url: str, **_kwargs):
        captured_urls.append(file_url)
        return TranscriptResult(text="真实转写", words=[], duration=3), "dashscope-asr"

    monkeypatch.setattr(service, "save_bytes", stored)
    monkeypatch.setattr(service, "get_accessible_url", accessible)
    monkeypatch.setattr(service.registry, "run_with_fallback", transcribed)

    async with SessionLocal() as db:
        result = await service.parse_upload(db, "media-url-user", "source video.mp4", b"video", None, 3)

    assert captured_urls == ["https://media.example.test/media/uploads/source%20video.mp4"]
    assert result.transcript is not None
    assert result.transcript.text == "真实转写"


async def test_real_acceptance_requires_public_media_base_url(monkeypatch) -> None:
    from app.core import storage

    monkeypatch.setattr(storage.settings, "media_public_base_url", "")

    with pytest.raises(storage.StorageConfigurationError, match="MEDIA_PUBLIC_BASE_URL"):
        await storage.get_accessible_url("uploads/source.mp4", require_public=True)


async def test_upload_asr_failure_returns_actionable_fallback(monkeypatch) -> None:
    from app.modules.content import service
    from app.providers.base import StepRecoverableError

    async def failing_asr(*_args, **_kwargs):
        raise StepRecoverableError("ASR 服务超时")

    monkeypatch.setattr(service.registry, "run_with_fallback", failing_asr)

    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as exc_info:
            await service.parse_upload(db, "asr-failure-user", "source.mp4", b"video", None, 3)

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["code"] == "ASR_FAILED"
    assert exc_info.value.detail["fallbacks"] == ["paste_text", "retry_upload"]


def test_upload_validation_rejects_unsupported_format() -> None:
    from app.modules.content.router import _validate_upload

    with pytest.raises(HTTPException) as exc_info:
        _validate_upload("payload.exe", b"data")

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "UNSUPPORTED_FORMAT"


def test_upload_validation_rejects_oversized_payload(monkeypatch) -> None:
    from app.modules.content import router

    monkeypatch.setattr(router, "_MAX_UPLOAD_BYTES", 4)

    with pytest.raises(HTTPException) as exc_info:
        router._validate_upload("source.mp4", b"12345")

    assert exc_info.value.status_code == 413
    assert exc_info.value.detail["code"] == "FILE_TOO_LARGE"


async def test_batch_rewrite_returns_ranked_variants(monkeypatch) -> None:
    from app.modules.content import service
    from app.providers.base import SimilarityResult

    generated = 0

    async def provider_call(_kind, _chain, method: str, *args, **_kwargs):
        nonlocal generated
        if method == "analyze_structure":
            return {"hook_type": "提问"}, "deepseek-v3"
        if method == "generate_outline":
            return "[钩子] 提出问题\n[CTA] 关注", "deepseek-v3"
        if method == "generate_script_variant":
            generated += 1
            return f"候选文案 {generated}", "deepseek-v3"
        if method == "check_similarity":
            score = 70.0 if args[0].endswith("1") else 30.0
            return SimilarityResult(score=score), "deepseek-v3"
        raise AssertionError(method)

    monkeypatch.setattr(service.registry, "run_with_fallback", provider_call)

    async with SessionLocal() as db:
        result = await service.batch_rewrite(
            db,
            "batch-user",
            "原始文案",
            "structure",
            2,
            None,
            None,
        )

    assert [item.text for item in result.items] == ["候选文案 2", "候选文案 1"]
    assert [item.similarity for item in result.items] == [30.0, 70.0]
    assert all(item.strategy for item in result.items)


def test_batch_rewrite_count_is_limited() -> None:
    from pydantic import ValidationError

    from app.modules.content.schemas import BatchRewriteIn

    assert BatchRewriteIn(text="测试", count=3).count == 3
    with pytest.raises(ValidationError):
        BatchRewriteIn(text="测试", count=1)
    with pytest.raises(ValidationError):
        BatchRewriteIn(text="测试", count=6)


async def test_deepseek_variant_uses_requested_strategy_and_temperature(monkeypatch) -> None:
    from app.providers.real import DeepSeekLLM

    captured: dict[str, object] = {}
    provider = DeepSeekLLM()

    async def chat(system: str, user: str, temperature: float = 0.8) -> str:
        captured.update(system=system, user=user, temperature=temperature)
        return "候选文案"

    monkeypatch.setattr(provider, "_chat", chat)

    result = await provider.generate_script_variant(
        "[钩子] 测试",
        "专业顾问",
        {"duration": 60, "cta_style": "私信咨询", "taboo_words": "绝对"},
        1.1,
        "转换表达视角",
    )

    assert result == "候选文案"
    assert captured["temperature"] == 1.1
    assert "转换表达视角" in str(captured["user"])


async def test_similarity_compares_rewrite_with_source_text() -> None:
    from app.providers.real import DeepSeekLLM

    source = "春天适合播种希望夏天适合认真成长秋天适合收获成果冬天适合沉淀复盘"
    unrelated = "客户真正关心的是结果路径交付节奏以及过程中每个风险点是否透明"
    provider = DeepSeekLLM()

    copied = await provider.check_similarity(source, source)
    rewritten = await provider.check_similarity(unrelated, source)

    assert copied.score == 100.0
    assert rewritten.score < copied.score
