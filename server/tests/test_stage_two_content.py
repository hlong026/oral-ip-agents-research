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


async def test_manual_edit_and_version_snapshot_commit_atomically(monkeypatch) -> None:
    """版本快照失败时不得先推进 Script.current_version。"""
    from app.modules.content import service

    async with SessionLocal() as db:
        created = await service.create_script(
            db,
            "stage2-atomic-version-user",
            None,
            "原始标题",
            "原始正文",
            "manual",
            None,
        )

    async def fail_append(*_args, **_kwargs):
        raise RuntimeError("version insert failed")

    monkeypatch.setattr(content_repo, "append_version", fail_append)
    async with SessionLocal() as db:
        with pytest.raises(RuntimeError, match="version insert failed"):
            await service.update_script(
                db,
                "stage2-atomic-version-user",
                created.id,
                title="不应落库的新标题",
                text="不应落库的新正文",
            )
        await db.rollback()

    async with SessionLocal() as db:
        unchanged = await content_repo.get(db, created.id, "stage2-atomic-version-user")

    assert unchanged is not None
    assert unchanged.title == "原始标题"
    assert unchanged.rewritten_text == ""
    assert unchanged.current_version == 1


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


async def test_pipeline_resolves_exact_saved_script_version() -> None:
    from app.modules.content import service as content_service
    from app.modules.pipeline.schemas import CreatePipelineIn
    from app.modules.pipeline.service import resolve_script_snapshot

    async with SessionLocal() as db:
        created = await content_service.create_script(
            db,
            "stage2-pipeline-script-user",
            None,
            "口播终稿",
            "来源原文",
            "manual",
            None,
        )
        saved = await content_service.update_script(
            db,
            "stage2-pipeline-script-user",
            created.id,
            title="口播终稿",
            text="人工确认后的最终口播稿",
        )
        script_id, version, snapshot = await resolve_script_snapshot(
            db,
            "stage2-pipeline-script-user",
            CreatePipelineIn(
                ipId="test-ip",
                scriptId=saved.id,
                scriptVersion=saved.currentVersion,
                scriptText="人工确认后的最终口播稿",
            ),
        )

    assert script_id == created.id
    assert version == 2
    assert snapshot == "人工确认后的最终口播稿"


async def test_pipeline_rejects_unsaved_script_text_against_version() -> None:
    from app.modules.content import service as content_service
    from app.modules.pipeline.schemas import CreatePipelineIn
    from app.modules.pipeline.service import resolve_script_snapshot

    async with SessionLocal() as db:
        created = await content_service.create_script(
            db,
            "stage2-unsaved-script-user",
            None,
            "口播稿",
            "已保存版本",
            "manual",
            None,
        )
        with pytest.raises(HTTPException) as exc:
            await resolve_script_snapshot(
                db,
                "stage2-unsaved-script-user",
                CreatePipelineIn(
                    ipId="test-ip",
                    scriptId=created.id,
                    scriptVersion=created.currentVersion,
                    scriptText="仅存在浏览器内的未保存修改",
                ),
            )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "SCRIPT_VERSION_MISMATCH"


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


def test_asr_detects_format_from_embedded_media() -> None:
    from app.providers.aliyun_asr import AliyunASR

    assert AliyunASR._guess_format("data:video/mp4;base64,AAAA") == "mp4"
    assert AliyunASR._guess_format("data:audio/mpeg;base64,AAAA") == "mp3"


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


async def test_asr_region_selects_matching_public_endpoint(monkeypatch) -> None:
    from app.providers import aliyun_asr

    async def fake_get_config(key: str, default: str = "") -> str:
        values = {
            "dashscope_api_key": "test-key",
            "dashscope_workspace_id": "",
            "dashscope_region": "ap-southeast-1",
        }
        return values.get(key, default)

    monkeypatch.setattr(aliyun_asr, "get_config", fake_get_config)

    config = await aliyun_asr.AliyunASR()._get_config()

    assert config["base_url"] == "https://dashscope-intl.aliyuncs.com"


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


async def test_short_upload_embeds_media_when_only_local_url_is_available(monkeypatch) -> None:
    from app.modules.content import service
    from app.providers.base import TranscriptResult

    captured_inputs: list[str] = []

    async def stored(_prefix: str, _filename: str, _data: bytes) -> str:
        return "uploads/source.mp4"

    async def local_url(_key: str, *, require_public: bool = False) -> str:
        assert require_public is False
        return "http://127.0.0.1:8000/media/uploads/source.mp4"

    async def threshold(_key: str, _default: int) -> int:
        return 300

    async def transcribed(_kind: str, _chain, _method: str, media_input: str, **_kwargs):
        captured_inputs.append(media_input)
        return TranscriptResult(text="本地短视频转写", words=[], duration=3), "dashscope-asr"

    monkeypatch.setattr(service, "save_bytes", stored)
    monkeypatch.setattr(service, "get_accessible_url", local_url)
    monkeypatch.setattr(service, "get_config_int", threshold, raising=False)
    monkeypatch.setattr(service.registry, "run_with_fallback", transcribed)

    async with SessionLocal() as db:
        result = await service.parse_upload(db, "local-media-user", "source.mp4", b"video", None, 3)

    assert captured_inputs == ["data:video/mp4;base64,dmlkZW8="]
    assert result.transcript is not None
    assert result.transcript.text == "本地短视频转写"


async def test_short_upload_extracts_audio_when_embedded_video_exceeds_provider_limit(monkeypatch) -> None:
    from app.modules.content import service
    from app.providers.base import TranscriptResult

    captured_inputs: list[str] = []

    async def stored(_prefix: str, _filename: str, _data: bytes) -> str:
        return "uploads/source.mp4"

    async def local_url(_key: str, *, require_public: bool = False) -> str:
        return "http://127.0.0.1:8000/media/uploads/source.mp4"

    async def threshold(_key: str, _default: int) -> int:
        return 300

    async def extracted(_data: bytes, _suffix: str) -> bytes:
        return b"audio"

    async def transcribed(_kind: str, _chain, _method: str, media_input: str, **_kwargs):
        captured_inputs.append(media_input)
        return TranscriptResult(text="压缩音轨转写", words=[], duration=3), "dashscope-asr"

    monkeypatch.setattr(service, "save_bytes", stored)
    monkeypatch.setattr(service, "get_accessible_url", local_url)
    monkeypatch.setattr(service, "get_config_int", threshold)
    monkeypatch.setattr(service, "extract_audio_bytes", extracted, raising=False)
    monkeypatch.setattr(service, "_MAX_ASR_DATA_URI_BYTES", 8, raising=False)
    monkeypatch.setattr(service.registry, "run_with_fallback", transcribed)

    async with SessionLocal() as db:
        result = await service.parse_upload(db, "large-local-media-user", "source.mp4", b"video", None, 3)

    assert captured_inputs == ["data:audio/mpeg;base64,YXVkaW8="]
    assert result.transcript is not None
    assert result.transcript.text == "压缩音轨转写"


async def test_long_upload_requires_public_media_url(monkeypatch) -> None:
    from app.core.storage import StorageConfigurationError
    from app.modules.content import service

    async def stored(_prefix: str, _filename: str, _data: bytes) -> str:
        return "uploads/source.mp4"

    async def inaccessible(_key: str, *, require_public: bool = False) -> str:
        if require_public:
            raise StorageConfigurationError("需要公网媒体地址")
        return "http://127.0.0.1:8000/media/uploads/source.mp4"

    async def threshold(_key: str, _default: int) -> int:
        return 300

    monkeypatch.setattr(service, "save_bytes", stored)
    monkeypatch.setattr(service, "get_accessible_url", inaccessible)
    monkeypatch.setattr(service, "get_config_int", threshold, raising=False)

    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as exc_info:
            await service.parse_upload(db, "long-media-user", "source.mp4", b"video", None, 301)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "MEDIA_PUBLIC_URL_REQUIRED"


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


async def test_url_parse_rejects_mock_parse_placeholder(monkeypatch) -> None:
    """上游解析全挂落到 mock-parse 时，不得用占位视频转写出假文案，必须返回可操作降级提示。"""
    from app.modules.content import service
    from app.providers.base import ParseResult

    async def disabled(_provider_name: str) -> bool:
        return False

    async def mock_chain(*_args, **_kwargs):
        return ParseResult(platform="douyin", title="占位", video_key="parsed/video.mp4.txt"), "mock-parse"

    monkeypatch.setattr(service.registry, "provider_enabled", disabled)
    monkeypatch.setattr(service.registry, "run_with_fallback", mock_chain)

    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as exc_info:
            await service.parse_url(db, "mock-guard-user", "https://www.douyin.com/video/mock-parse-guard", None)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "LINK_SOURCE_UNAVAILABLE"
    assert exc_info.value.detail["fallbacks"] == ["paste_text", "upload_file"]


async def test_url_parse_mock_asr_falls_back_to_platform_text(monkeypatch) -> None:
    """真实直链被 Mock ASR 兜底时，改用平台发布文本并标记 degraded。"""
    from types import SimpleNamespace

    from app.modules.content import service
    from app.providers.base import TranscriptResult
    from app.providers.douyidou import DouyidouParser, DouyidouParseResult

    async def enabled(_provider_name: str) -> bool:
        return True

    async def fake_douyidou(self, _url: str, is_title: int = 0) -> DouyidouParseResult:
        del self, is_title
        return DouyidouParseResult(
            platform="douyin",
            title="真实标题",
            text="平台发布文本兜底内容",
            video_url="https://cdn.example.com/real-video.mp4",
        )

    async def mock_asr(_kind: str, _chain, _method: str, *_args, **_kwargs):
        return TranscriptResult(text="MOCK 占位文案", words=[], duration=10), "mock-faster-whisper"

    saved: dict[str, object] = {}

    async def fake_create_script(_db, **kwargs):
        saved.update(kwargs)
        return SimpleNamespace(id="script-text-fallback")

    monkeypatch.setattr(service.registry, "provider_enabled", enabled)
    monkeypatch.setattr(DouyidouParser, "parse_url_full", fake_douyidou)
    monkeypatch.setattr(service.registry, "run_with_fallback", mock_asr)
    monkeypatch.setattr(service, "_create_script_with_source_version", fake_create_script)

    parsed = await service.parse_url(
        None,  # type: ignore[arg-type]
        "mock-asr-user",
        "https://www.douyin.com/video/mock-asr-guard",
        None,
        42,
    )

    assert parsed.degraded is True
    assert parsed.transcript is not None
    assert parsed.transcript.text == "平台发布文本兜底内容"
    assert saved["original_text"] == "平台发布文本兜底内容"


async def test_url_parse_mock_asr_without_platform_text_raises(monkeypatch) -> None:
    """无平台文本可兜底时，Mock ASR 结果必须报错而非静默落库假文案。"""
    from app.modules.content import service
    from app.providers.base import ParseResult, TranscriptResult

    async def disabled(_provider_name: str) -> bool:
        return False

    async def routed(kind: str, _chain, _method: str, *_args, **_kwargs):
        if kind == "parse":
            return (
                ParseResult(platform="douyin", title="", video_key="https://cdn.example.com/v.mp4"),
                "third-party-parse",
            )
        return TranscriptResult(text="MOCK 占位文案", words=[], duration=10), "mock-faster-whisper"

    monkeypatch.setattr(service.registry, "provider_enabled", disabled)
    monkeypatch.setattr(service.registry, "run_with_fallback", routed)

    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as exc_info:
            await service.parse_url(db, "mock-asr-fail-user", "https://www.douyin.com/video/mock-asr-fail", None, 42)

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["code"] == "ASR_FAILED"
    assert exc_info.value.detail["fallbacks"] == ["paste_text", "upload_file"]


async def test_upload_rejects_mock_asr_placeholder(monkeypatch) -> None:
    """真实上传文件被 Mock ASR 兜底时，占位文案不得落库，必须报 ASR_FAILED。"""
    from app.modules.content import service
    from app.providers.base import TranscriptResult

    async def mock_asr(*_args, **_kwargs):
        return TranscriptResult(text="MOCK 占位文案", words=[], duration=10), "mock-faster-whisper"

    monkeypatch.setattr(service.registry, "run_with_fallback", mock_asr)

    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as exc_info:
            await service.parse_upload(db, "mock-upload-user", "source.mp4", b"video", None, 3)

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
