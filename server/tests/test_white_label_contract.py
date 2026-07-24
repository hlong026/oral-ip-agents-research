"""用户可见界面的供应商品牌白标化回归测试。"""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.main import app, http_exc, provider_exc
from app.modules.content import jobs as content_jobs
from app.modules.content import service as content_service
from app.modules.notify import service as notify_service
from app.modules.pipeline import service as pipeline_service
from app.providers import registry as registry_module
from app.providers.base import StepRecoverableError
from app.providers.registry import ProviderRegistry

REPO_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_USER_VISIBLE_BRANDS = (
    "minimax",
    "speech-02",
    "hifly",
    "飞影",
    "dashscope",
    "阿里云",
    "aliyun",
    "douyidou",
    "deepseek",
    "豆包",
    "云雾",
    "cosyvoice",
    "gpt-sovits",
    "fun-asr",
    "whisper",
    "heygem",
    "ffmpeg",
    "redis",
)


def _assert_white_label(value: object) -> None:
    text = json.dumps(value, ensure_ascii=False).casefold()
    leaked = [brand for brand in FORBIDDEN_USER_VISIBLE_BRANDS if brand.casefold() in text]
    assert leaked == []


def test_user_facing_web_sources_do_not_name_providers() -> None:
    web_sources = [
        path
        for pattern in ("*.ts", "*.tsx")
        for path in (REPO_ROOT / "apps/web/src").rglob(pattern)
        if "__tests__" not in path.parts
    ]
    paths = [
        *sorted(web_sources),
        *sorted((REPO_ROOT / "docs/ui-mockup").glob("*.html")),
    ]
    leaks: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8").casefold()
        for brand in FORBIDDEN_USER_VISIBLE_BRANDS:
            if brand.casefold() in text:
                leaks.append(f"{path.relative_to(REPO_ROOT)}: {brand}")
    assert leaks == []


@pytest.mark.asyncio
async def test_provider_exception_response_hides_provider_details() -> None:
    request = Request({"type": "http", "method": "POST", "path": "/api/v1/content/parse", "headers": []})

    response = await provider_exc(request, StepRecoverableError("DashScope ASR quota exhausted"))

    payload = json.loads(response.body)
    assert payload["detail"]["message"] == "外部服务暂不可用，请稍后重试"
    _assert_white_label(payload)


@pytest.mark.asyncio
async def test_http_exception_response_hides_branded_message() -> None:
    request = Request({"type": "http", "method": "POST", "path": "/api/v1/voices/clone", "headers": []})

    response = await http_exc(
        request,
        HTTPException(
            422,
            detail={"code": "CLONE_FAILED", "message": "飞影额度不足", "retryable": True},
        ),
    )

    payload = json.loads(response.body)
    assert payload["detail"] == {
        "code": "CLONE_FAILED",
        "message": "处理失败，请稍后重试",
        "retryable": True,
    }
    _assert_white_label(payload)


@pytest.mark.asyncio
async def test_admin_http_exception_keeps_provider_diagnostics() -> None:
    request = Request(
        {
            "type": "http",
            "method": "PUT",
            "path": "/api/admin/v1/providers/settings",
            "headers": [],
        }
    )

    response = await http_exc(
        request,
        HTTPException(
            422,
            detail={"code": "PROVIDER_SETTING_INVALID", "message": "DashScope 地域无效"},
        ),
    )

    payload = json.loads(response.body)
    assert payload["detail"]["message"] == "DashScope 地域无效"


@pytest.mark.asyncio
async def test_provider_fallback_event_hides_provider_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[dict] = []

    class FailingProvider:
        name = "deepseek-v3"

        async def rewrite(self) -> str:
            raise StepRecoverableError("DeepSeek request failed")

    class BackupProvider:
        name = "hifly-voice"

        async def rewrite(self) -> str:
            return "ok"

    async def enabled(_provider_name: str) -> bool:
        return True

    async def capture(_channel: str, payload: dict) -> None:
        events.append(payload)

    registry = ProviderRegistry.__new__(ProviderRegistry)
    registry.provider_enabled = enabled
    monkeypatch.setattr(registry_module, "publish", capture)

    result, provider_name = await registry.run_with_fallback(
        "llm",
        [FailingProvider(), BackupProvider()],
        "rewrite",
        task_id="task-1",
    )

    assert result == "ok"
    assert provider_name == "hifly-voice"
    assert len(events) == 1
    assert "to" not in events[0]
    _assert_white_label(events[0])


@pytest.mark.asyncio
async def test_notification_outputs_hide_current_and_historical_provider_names(monkeypatch: pytest.MonkeyPatch) -> None:
    stored: list[dict] = []
    events: list[dict] = []

    async def capture_store(_db, **payload) -> None:
        stored.append(payload)

    async def capture_event(_channel: str, payload: dict) -> None:
        events.append(payload)

    monkeypatch.setattr(notify_service.repo, "create", capture_store)
    monkeypatch.setattr(notify_service, "publish", capture_event)

    await notify_service.notify_user(
        SimpleNamespace(),
        "user-1",
        "error",
        "HiFly 声音任务失败",
        "已从 DeepSeek 切换到 DashScope，请稍后重试",
    )

    assert stored[0]["title"] == "HiFly 声音任务失败"
    assert stored[0]["body"] == "已从 DeepSeek 切换到 DashScope，请稍后重试"
    _assert_white_label(events[0])

    historical = SimpleNamespace(
        id="notice-1",
        level="error",
        title="飞影任务失败",
        body="MiniMax Speech-02 暂不可用",
        read=False,
        created_at=datetime.now(UTC),
    )
    _assert_white_label(notify_service.to_out(historical).model_dump())


def test_public_openapi_hides_legacy_provider_webhook_path() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/webhooks/provider-callback" in paths
    assert "/api/v1/webhooks/hifly" not in paths


def test_background_job_error_hides_provider_details() -> None:
    message = content_jobs._error_message(StepRecoverableError("HiFly voice task failed"))

    assert message == "外部服务暂不可用，请稍后重试"
    _assert_white_label(message)


def test_content_job_output_hides_legacy_provider_metadata_and_error() -> None:
    now = datetime.now(UTC)
    job = SimpleNamespace(
        id="job-1",
        kind="rewrite",
        status="failed",
        progress=80,
        stage="rewrite",
        result_json=json.dumps(
            {
                "text": "用户正文可以原样保留",
                "providerName": "deepseek-v3",
            },
            ensure_ascii=False,
        ),
        error="DeepSeek upstream timeout",
        created_at=now,
        updated_at=now,
    )

    output = content_jobs.to_out(job)
    payload = output.model_dump()

    assert payload["result"]["providerName"] == "智能文案引擎"
    assert payload["result"]["text"] == "用户正文可以原样保留"
    assert payload["error"] == "处理失败，请稍后重试"
    _assert_white_label(payload)


def test_pipeline_output_hides_provider_fields_and_messages() -> None:
    now = datetime.now(UTC)
    task = SimpleNamespace(
        id="task-1",
        ip_id="ip-1",
        title="测试任务",
        source_url="https://example.com",
        mode="auto",
        status="failed",
        steps_json=json.dumps(
            [
                {
                    "step": "voice",
                    "status": "failed",
                    "progress": 10,
                    "message": "飞影 voice timeout",
                    "compute": "cloud",
                    "provider": "hifly-voice",
                    "quotaCost": 0,
                    "artifacts": {"provider_task": "hifly-123"},
                    "startedAt": now.isoformat(),
                    "finishedAt": now.isoformat(),
                    "durationMs": 12,
                }
            ],
            ensure_ascii=False,
        ),
        current_step="voice",
        compute="cloud",
        quota_cost=0,
        error="voice: HiFly voice timeout",
        artifacts_json=json.dumps(
            {
                "cover_key": "cover.png",
                "avatar_provider": "hifly-avatar",
                "safe_asset": "asset-1",
            }
        ),
        batch_id=None,
        created_at=now,
        updated_at=now,
    )

    output = pipeline_service.to_out(task)
    payload = output.model_dump()

    assert payload["steps"][0]["provider"] == ""
    assert "provider_task" not in payload["steps"][0]["artifacts"]
    assert "avatar_provider" not in payload["artifacts"]
    assert payload["artifacts"]["safe_asset"] == "asset-1"
    _assert_white_label(payload)


def test_script_output_uses_neutral_model_label() -> None:
    now = datetime.now(UTC)
    script = SimpleNamespace(
        id="script-1",
        title="测试文案",
        source_url="",
        platform="manual",
        original_text="原文",
        rewritten_text="改写文",
        similarity_score=10,
        current_version=2,
        model_name="deepseek-v3",
        prompt_version="v1",
        status="ready",
        created_at=now,
    )

    output = content_service.to_out(script)

    assert output.modelName == "智能文案引擎"
    _assert_white_label(output.model_dump())
