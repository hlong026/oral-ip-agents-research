"""管理员控制面、套餐目录和积分报价的契约测试。"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.core.db import SessionLocal
from app.core.security import decode_token, hash_password
from app.modules.auth.models import User
from app.modules.catalog.service import LEGACY_MODULE_PRICES, MODULE_BILLING_UNITS
from tests.helpers import DEFAULT_FINGERPRINT, bind_used_code, code_login


def _phone() -> str:
    return f"138{uuid.uuid4().hex[:8]}"


async def _create_user(*, role: str) -> tuple[str, str, str]:
    phone = _phone()
    password = "Test@12345"
    async with SessionLocal() as db:
        user = User(
            phone=phone,
            password_hash=hash_password(password),
            nickname="管理员" if role == "admin" else "普通用户",
            avatar_char="管" if role == "admin" else "用",
            role=role,
            plan_type="trial" if role == "user" else "none",
            plan_expires_at=datetime.now(UTC) + timedelta(days=30) if role == "user" else None,
        )
        db.add(user)
        await db.commit()
        user_id = user.id
    return user_id, phone, password


async def _login(client: AsyncClient, *, role: str) -> dict[str, str]:
    user_id, phone, password = await _create_user(role=role)
    if role == "admin":
        response = await client.post("/api/admin/v1/auth/login", json={"phone": phone, "password": password})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['accessToken']}"}
    from app.modules.avatar.models import Avatar
    from app.modules.ipasset.models import Persona
    from app.modules.voice.models import Voice

    async with SessionLocal() as db:
        voice = Voice(
            user_id=user_id,
            name="测试声音",
            status="ready",
            provider_voice_id=f"provider-voice-{user_id[:12]}",
        )
        avatar = Avatar(
            user_id=user_id,
            name="测试数字人",
            status="ready",
            provider_avatar_id=f"provider-avatar-{user_id[:12]}",
        )
        db.add_all([voice, avatar])
        await db.flush()
        db.add(
            Persona(
                id=user_id,
                user_id=user_id,
                name="测试人设",
                voice_id=voice.id,
                avatar_id=avatar.id,
                is_active=True,
            )
        )
        await db.commit()
    tokens = await code_login(client, await bind_used_code(user_id))
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


async def _user_login_for_role(client: AsyncClient, *, role: str) -> dict:
    """以用户面（激活码）身份登录，取 user-audience 令牌。"""
    user_id, _phone, _password = await _create_user(role=role)
    return await code_login(client, await bind_used_code(user_id))


def _annual_plan_payload(code: str, *, audience: str = "public") -> dict:
    return {
        "code": code,
        "name": "标准年包",
        "subtitle": "适合稳定创作",
        "description": "每月发放积分，支持数字人视频",
        "badge": "推荐",
        "skuType": "annual_bundle" if audience == "public" else "internal_annual",
        "audience": audience,
        "durationDays": 365,
        "monthlyPoints": 1000,
        "oneTimePoints": 0,
        "listPriceCents": 199900,
        "displayPriceCents": 169900,
        "entitlements": ["digital_human", "voice_clone", "1080p_export"],
        "maxConcurrency": 2,
        "maxResolution": "1080p",
        "purchaseInstructions": "联系管理员获取激活码",
    }


def test_legacy_price_catalog_preserves_existing_pipeline_step_prices():
    prices = {item[0]: item[3] for item in LEGACY_MODULE_PRICES}

    assert prices == {
        "topic_generation": 1,
        "asr": 2,
        "script_generation": 2,
        "tts": 8,
        "voice_clone": 10,
        "digital_human": 20,
        "hd_export": 3,
    }


def test_provider_modules_only_accept_verifiable_billing_units():
    assert MODULE_BILLING_UNITS["tts"] == {"per_action", "per_1k_chars", "per_1k_tokens"}
    assert MODULE_BILLING_UNITS["voice_clone"] == {"per_action", "per_asset"}
    assert MODULE_BILLING_UNITS["asr"] == {"per_action", "per_minute", "per_second"}


def test_operation_quote_rejects_same_module_with_underreported_quantity():
    from app.modules.billing.models import PriceQuote
    from app.modules.billing.service import _validate_quote_matches_operation

    quote = PriceQuote(
        id="quote-test",
        user_id="user-test",
        catalog_version_id="catalog-test",
        price_version="test-v1",
        items_json='[{"module":"script_generation","unit":"per_1k_chars","quantity":1,"points":1}]',
        estimated_points=1,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    with pytest.raises(HTTPException) as exc:
        _validate_quote_matches_operation(
            quote,
            {
                "module": "script_generation",
                "measures": {"characters": 100, "tokens": 50, "assets": 1},
            },
        )
    assert exc.value.detail["code"] == "QUOTE_OPERATION_MISMATCH"


async def test_admin_can_list_and_release_unknown_provider_submission(client: AsyncClient) -> None:
    from sqlalchemy import select

    from app.core.audit import AuditLog
    from app.modules.billing.models import CreditReservation
    from app.modules.pipeline.models import PipelineTask

    headers = await _login(client, role="admin")
    user_id, _phone_value, _password = await _create_user(role="user")
    async with SessionLocal() as db:
        reservation = CreditReservation(
            user_id=user_id,
            quote_id=f"quote-{uuid.uuid4().hex}",
            reserved_points=0,
            status="reserved",
        )
        db.add(reservation)
        await db.flush()
        task = PipelineTask(
            user_id=user_id,
            ip_id="persona-test",
            title="等待对账的任务",
            status="reconciliation_required",
            current_step="voice",
            reservation_id=reservation.id,
            error="外部服务结果未知",
        )
        db.add(task)
        await db.flush()
        reservation.task_id = task.id
        await db.commit()
        task_id = task.id
        reservation_id = reservation.id

    listed = await client.get("/api/admin/v1/reconciliations", headers=headers)
    assert listed.status_code == 200, listed.text
    assert any(item["id"] == task_id and item["kind"] == "pipeline" for item in listed.json()["items"])

    resolved = await client.post(
        f"/api/admin/v1/reconciliations/pipeline/{task_id}",
        headers=headers,
        json={"action": "release", "reason": "供应商后台确认未创建任务"},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["reservationStatus"] == "released"

    async with SessionLocal() as db:
        task = await db.get(PipelineTask, task_id)
        reservation = await db.get(CreditReservation, reservation_id)
        audit = (
            (
                await db.execute(
                    select(AuditLog)
                    .where(AuditLog.event == "provider_reconciliation_resolved", AuditLog.task_id == task_id)
                    .order_by(AuditLog.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
    assert task is not None and task.status == "failed"
    assert reservation is not None and reservation.status == "released"
    assert audit is not None and "action=release" in audit.detail


async def test_failure_recovery_rolls_back_before_releasing(monkeypatch: pytest.MonkeyPatch):
    from app.modules.billing import service as billing_service

    class FailedSession:
        rolled_back = False

        async def rollback(self) -> None:
            self.rolled_back = True

    failed_db = FailedSession()

    async def release_after_rollback(db, reservation_id: str, user_id: str):
        assert db is failed_db
        assert db.rolled_back is True
        assert reservation_id == "reservation-test"
        assert user_id == "user-test"
        return type("Recovered", (), {"status": "released"})()

    monkeypatch.setattr(billing_service, "release_reservation", release_after_rollback)

    recovered = await billing_service.recover_reservation_after_failure(
        failed_db,  # type: ignore[arg-type]
        "reservation-test",
        "user-test",
    )

    assert recovered is not None
    assert recovered.status == "released"


async def _create_and_publish_plan(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    code: str,
    audience: str = "public",
) -> dict:
    created = await client.post(
        "/api/admin/v1/plans",
        headers=headers,
        json=_annual_plan_payload(code, audience=audience),
    )
    assert created.status_code == 201, created.text
    plan = created.json()
    published = await client.post(f"/api/admin/v1/plans/{plan['id']}/publish", headers=headers)
    assert published.status_code == 200, published.text
    return published.json()


async def test_open_registration_is_disabled(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/register",
        json={"phone": _phone(), "password": "Test@12345", "nickname": "绕过激活"},
    )
    assert response.status_code == 404


async def test_provider_backed_content_endpoint_requires_login(client: AsyncClient):
    response = await client.post("/api/v1/content/topics", json={"keyword": "口播"})
    assert response.status_code == 401


async def test_provider_backed_content_operation_requires_and_settles_quote(
    client: AsyncClient,
    monkeypatch,
):
    headers = await _login(client, role="user")
    token = headers["Authorization"].removeprefix("Bearer ")
    user_id = str(decode_token(token)["sub"])

    from app.modules.billing.service import grant_points

    async with SessionLocal() as db:
        await grant_points(
            db,
            user_id,
            20,
            source_type="manual",
            source_id=f"test-{uuid.uuid4().hex}",
            expires_at=datetime.now(UTC) + timedelta(days=30),
            commit=True,
        )

    quote = await client.post(
        "/api/v1/billing/price-preview",
        headers=headers,
        json={"items": [{"module": "topic_generation", "quantity": 1}]},
    )
    assert quote.status_code == 200, quote.text
    failed_quote = await client.post(
        "/api/v1/billing/price-preview",
        headers=headers,
        json={"items": [{"module": "topic_generation", "quantity": 1}]},
    )
    assert failed_quote.status_code == 200, failed_quote.text
    wrong_module_quote = await client.post(
        "/api/v1/billing/price-preview",
        headers=headers,
        json={"items": [{"module": "script_generation", "quantity": 1}]},
    )
    assert wrong_module_quote.status_code == 200, wrong_module_quote.text
    settlement_quote = await client.post(
        "/api/v1/billing/price-preview",
        headers=headers,
        json={"items": [{"module": "topic_generation", "quantity": 1}]},
    )
    assert settlement_quote.status_code == 200, settlement_quote.text

    from app.core.config import get_settings
    from app.modules.content import router as content_router

    monkeypatch.setattr(get_settings(), "app_env", "prod")

    without_quote = await client.post(
        "/api/v1/content/topics",
        headers=headers,
        json={"keyword": "口播"},
    )
    assert without_quote.status_code == 409
    assert without_quote.json()["detail"]["code"] == "QUOTE_REQUIRED"

    mismatched = await client.post(
        "/api/v1/content/topics",
        headers=headers,
        json={"keyword": "口播", "quoteId": wrong_module_quote.json()["quoteId"]},
    )
    assert mismatched.status_code == 409
    assert mismatched.json()["detail"]["code"] == "QUOTE_OPERATION_MISMATCH"

    async def fake_topics(_keyword: str) -> list[str]:
        return ["选题一"]

    monkeypatch.setattr(content_router, "topics", fake_topics)
    billed = await client.post(
        "/api/v1/content/topics",
        headers=headers,
        json={"keyword": "口播", "quoteId": quote.json()["quoteId"]},
    )
    assert billed.status_code == 200, billed.text
    assert billed.json() == {"topics": ["选题一"]}

    balance = await client.get("/api/v1/billing/balance", headers=headers)
    usage = await client.get("/api/v1/billing/usage", headers=headers)
    assert balance.json()["balance"] == 19
    assert usage.json()["items"][0]["step"] == "topic_generation"
    assert usage.json()["items"][0]["points"] == 1

    async def failing_topics(_keyword: str) -> list[str]:
        raise HTTPException(503, detail={"code": "UPSTREAM_FAILED", "message": "上游失败"})

    monkeypatch.setattr(content_router, "topics", failing_topics)
    failed = await client.post(
        "/api/v1/content/topics",
        headers=headers,
        json={"keyword": "口播", "quoteId": failed_quote.json()["quoteId"]},
    )
    assert failed.status_code == 503
    balance_after_failure = await client.get("/api/v1/billing/balance", headers=headers)
    assert balance_after_failure.json()["balance"] == 19

    from app.modules.billing import service as billing_service

    async def failing_settlement(*_args, **_kwargs) -> int:
        raise HTTPException(503, detail={"code": "SETTLEMENT_DOWN", "message": "结算失败"})

    monkeypatch.setattr(content_router, "topics", fake_topics)
    monkeypatch.setattr(billing_service, "settle_reservation", failing_settlement)
    settlement_failed = await client.post(
        "/api/v1/content/topics",
        headers=headers,
        json={"keyword": "口播", "quoteId": settlement_quote.json()["quoteId"]},
    )
    assert settlement_failed.status_code == 503
    balance_after_settlement_failure = await client.get("/api/v1/billing/balance", headers=headers)
    assert balance_after_settlement_failure.json()["balance"] == 19


async def test_upload_transcription_only_deducts_points_after_success(
    client: AsyncClient,
    monkeypatch,
):
    headers = await _login(client, role="user")
    token = headers["Authorization"].removeprefix("Bearer ")
    user_id = str(decode_token(token)["sub"])

    from app.modules.billing.service import grant_points

    async with SessionLocal() as db:
        await grant_points(
            db,
            user_id,
            10,
            source_type="manual",
            source_id=f"test-{uuid.uuid4().hex}",
            expires_at=datetime.now(UTC) + timedelta(days=30),
            commit=True,
        )

    async def create_quote() -> str:
        response = await client.post(
            "/api/v1/billing/price-preview",
            headers=headers,
            json={"items": [{"module": "asr", "quantity": 1}]},
        )
        assert response.status_code == 200, response.text
        return str(response.json()["quoteId"])

    failed_quote_id = await create_quote()
    successful_quote_id = await create_quote()

    from app.modules.content import router as content_router
    from app.modules.content.schemas import ParseOut, TranscriptOut

    async def verified_media(_key: str) -> dict:
        return {
            "format": {"duration": "60"},
            "streams": [{"codec_type": "video", "codec_name": "h264"}],
        }

    async def failing_parse(*_args, **_kwargs):
        raise HTTPException(502, detail={"code": "ASR_FAILED", "message": "语音识别失败"})

    monkeypatch.setattr(content_router, "probe_media_key", verified_media)
    monkeypatch.setattr(content_router, "parse_upload", failing_parse)

    failed = await client.post(
        "/api/v1/content/parse",
        headers=headers,
        data={"quoteId": failed_quote_id},
        files={"file": ("sample.mp4", b"video", "video/mp4")},
    )
    assert failed.status_code == 502, failed.text
    balance_after_failure = await client.get("/api/v1/billing/balance", headers=headers)
    usage_after_failure = await client.get("/api/v1/billing/usage", headers=headers)
    assert balance_after_failure.json()["balance"] == 10
    assert usage_after_failure.json()["items"] == []

    async def successful_parse(*_args, **_kwargs) -> ParseOut:
        return ParseOut(
            transcript=TranscriptOut(text="转写成功", words=[], duration=60),
            degraded=False,
        )

    monkeypatch.setattr(content_router, "parse_upload", successful_parse)
    succeeded = await client.post(
        "/api/v1/content/parse",
        headers=headers,
        data={"quoteId": successful_quote_id},
        files={"file": ("sample.mp4", b"video", "video/mp4")},
    )
    assert succeeded.status_code == 200, succeeded.text

    balance_after_success = await client.get("/api/v1/billing/balance", headers=headers)
    usage_after_success = await client.get("/api/v1/billing/usage", headers=headers)
    assert balance_after_success.json()["balance"] == 8
    assert usage_after_success.json()["items"][0]["step"] == "asr"
    assert usage_after_success.json()["items"][0]["points"] == 2


async def test_async_voice_clone_settles_only_after_provider_success(
    client: AsyncClient,
    monkeypatch,
):
    headers = await _login(client, role="user")
    token = headers["Authorization"].removeprefix("Bearer ")
    user_id = str(decode_token(token)["sub"])

    from app.modules.billing.models import PriceQuote
    from app.modules.billing.service import grant_points

    quote_id = f"quote_{uuid.uuid4().hex}"
    async with SessionLocal() as db:
        await grant_points(
            db,
            user_id,
            20,
            source_type="manual",
            source_id=f"test-{uuid.uuid4().hex}",
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        db.add(
            PriceQuote(
                id=quote_id,
                user_id=user_id,
                catalog_version_id="test-catalog",
                price_version="test-v1",
                items_json='[{"module":"voice_clone","unit":"per_asset","quantity":1,"points":5}]',
                estimated_points=5,
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
        )
        await db.commit()

    from app.modules.voice import repository as voice_repo
    from app.modules.voice import router as voice_router
    from app.modules.voice.service import to_out

    async def fake_clone(
        db,
        current_user_id,
        name,
        _consent_token,
        sample_key,
        language,
        reservation_id,
    ):
        voice = await voice_repo.create(
            db,
            user_id=current_user_id,
            name=name,
            source="clone",
            provider="mock",
            provider_voice_id="",
            provider_task_id="mock-task",
            reservation_id=reservation_id,
            sample_key=sample_key,
            language=language,
            status="training",
        )
        return to_out(voice)

    monkeypatch.setattr(voice_router, "clone_voice", fake_clone)

    async def verified_voice_sample(_data: bytes, _suffix: str) -> dict:
        return {
            "format": {"duration": "10"},
            "streams": [{"codec_type": "audio", "codec_name": "pcm_s16le"}],
        }

    monkeypatch.setattr(voice_router, "probe_media_bytes_info", verified_voice_sample)

    submitted = await client.post(
        "/api/v1/voices/clone",
        headers=headers,
        data={"name": "测试声音", "consentToken": "consent-test", "quoteId": quote_id},
        files={"file": ("sample.wav", b"voice-sample", "audio/wav")},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "training"

    balance_while_training = await client.get("/api/v1/billing/balance", headers=headers)
    usage_while_training = await client.get("/api/v1/billing/usage", headers=headers)
    assert balance_while_training.json()["balance"] == 15
    assert usage_while_training.json()["items"] == []

    from app.modules.voice import service as voice_service

    async def fake_status(*_args, **_kwargs):
        # mock 模式返回本地 demo 路径：demo 就绪后轮询侧才会转 pending_confirm
        return {"status": 3, "voice_id": "mock-voice", "demo_url": "/media/voice-demos/demo.mp3"}, "mock"

    monkeypatch.setattr(voice_service.registry, "run_with_fallback", fake_status)

    async def deliver_webhook() -> None:
        async with SessionLocal() as callback_db:
            await voice_service.handle_voice_callback(callback_db, "mock-task", 3, "mock-voice", "")

    completed, _ = await asyncio.gather(
        client.get(
            f"/api/v1/voices/{submitted.json()['id']}/status",
            headers=headers,
        ),
        deliver_webhook(),
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "pending_confirm"

    await deliver_webhook()

    usage = await client.get("/api/v1/billing/usage", headers=headers)
    assert len(usage.json()["items"]) == 1
    assert usage.json()["items"][0]["step"] == "voice_clone"
    assert usage.json()["items"][0]["points"] == 5


async def test_duplicate_avatar_callbacks_settle_reservation_once(
    client: AsyncClient,
) -> None:
    headers = await _login(client, role="user")
    token = headers["Authorization"].removeprefix("Bearer ")
    user_id = str(decode_token(token)["sub"])

    from sqlalchemy import func, select

    from app.modules.avatar.models import Avatar
    from app.modules.avatar.service import handle_avatar_callback
    from app.modules.billing.models import CreditLedger, PriceQuote
    from app.modules.billing.service import grant_points, reserve_metered_operation

    quote_id = f"quote_{uuid.uuid4().hex}"
    provider_task_id = f"avatar-task-{uuid.uuid4().hex}"
    async with SessionLocal() as db:
        await grant_points(
            db,
            user_id,
            20,
            source_type="manual",
            source_id=f"test-{uuid.uuid4().hex}",
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        db.add(
            PriceQuote(
                id=quote_id,
                user_id=user_id,
                catalog_version_id="test-catalog",
                price_version="test-v1",
                items_json='[{"module":"digital_human","unit":"per_asset","quantity":1,"points":5}]',
                estimated_points=5,
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
        )
        await db.commit()
        reservation_id = await reserve_metered_operation(db, user_id, quote_id, "digital_human", {"assets": 1})
        db.add(
            Avatar(
                user_id=user_id,
                name="测试数字人",
                provider="mock",
                provider_task_id=provider_task_id,
                reservation_id=reservation_id,
                status="training",
            )
        )
        await db.commit()

    async def deliver() -> None:
        async with SessionLocal() as callback_db:
            await handle_avatar_callback(callback_db, provider_task_id, 3, "mock-avatar")

    await asyncio.gather(deliver(), deliver())
    await deliver()

    async with SessionLocal() as db:
        settlement_count = await db.scalar(
            select(func.count(CreditLedger.id)).where(
                CreditLedger.reference_id == reservation_id,
                CreditLedger.event_type == "settle",
            )
        )
    assert settlement_count == 1


async def test_user_cannot_access_admin_control_plane(client: AsyncClient):
    headers = await _login(client, role="user")

    plans = await client.get("/api/admin/v1/plans", headers=headers)
    providers = await client.get("/api/admin/v1/providers", headers=headers)

    assert plans.status_code == 403
    assert providers.status_code == 403


async def test_admin_role_with_user_audience_cannot_access_admin_control_plane(client: AsyncClient):
    tokens = await _user_login_for_role(client, role="admin")
    response = await client.get(
        "/api/admin/v1/plans",
        headers={"Authorization": f"Bearer {tokens['accessToken']}"},
    )
    assert response.status_code == 403


async def test_admin_audience_token_cannot_access_user_data_plane(client: AsyncClient):
    headers = await _login(client, role="admin")

    response = await client.get("/api/v1/billing/balance", headers=headers)

    assert response.status_code == 403


async def test_disabled_user_access_token_stops_working_immediately(client: AsyncClient):
    admin_headers = await _login(client, role="admin")
    user_tokens = await _user_login_for_role(client, role="user")
    user_id = str(decode_token(user_tokens["accessToken"])["sub"])

    disabled = await client.patch(
        f"/api/admin/v1/users/{user_id}",
        headers=admin_headers,
        json={"isActive": False},
    )
    response = await client.get(
        "/api/v1/billing/balance",
        headers={"Authorization": f"Bearer {user_tokens['accessToken']}"},
    )

    assert disabled.status_code == 200, disabled.text
    assert response.status_code == 403


async def test_admin_credit_adjustment_uses_ledger_instead_of_raw_balance_edit(client: AsyncClient):
    admin_headers = await _login(client, role="admin")
    user_tokens = await _user_login_for_role(client, role="user")
    user_id = str(decode_token(user_tokens["accessToken"])["sub"])

    granted = await client.post(
        f"/api/admin/v1/users/{user_id}/credits/adjust",
        headers=admin_headers,
        json={"points": 100, "reason": "客户补偿积分"},
    )
    deducted = await client.post(
        f"/api/admin/v1/users/{user_id}/credits/adjust",
        headers=admin_headers,
        json={"points": -30, "reason": "纠正重复发放"},
    )

    assert granted.status_code == 200, granted.text
    assert deducted.status_code == 200, deducted.text
    assert deducted.json()["balance"] == 70

    from sqlalchemy import func, select

    from app.modules.billing.models import CreditLedger

    async with SessionLocal() as db:
        ledger_count = await db.scalar(
            select(func.count(CreditLedger.id)).where(
                CreditLedger.user_id == user_id,
                CreditLedger.event_type == "adjustment",
            )
        )
    assert ledger_count == 2


async def test_refresh_token_is_rotated_and_old_token_cannot_be_reused(client: AsyncClient):
    tokens = await _user_login_for_role(client, role="user")

    first = await client.post(
        "/api/v1/auth/refresh",
        json={"refreshToken": tokens["refreshToken"], "deviceFingerprint": DEFAULT_FINGERPRINT},
    )
    replay = await client.post(
        "/api/v1/auth/refresh",
        json={"refreshToken": tokens["refreshToken"], "deviceFingerprint": DEFAULT_FINGERPRINT},
    )

    assert first.status_code == 200, first.text
    assert replay.status_code == 401


async def test_published_public_plan_is_visible_but_internal_plan_is_hidden(client: AsyncClient):
    admin_headers = await _login(client, role="admin")
    public_code = f"ANNUAL_{uuid.uuid4().hex[:8].upper()}"
    internal_code = f"INTERNAL_{uuid.uuid4().hex[:8].upper()}"
    public_plan = await _create_and_publish_plan(client, admin_headers, code=public_code)
    await _create_and_publish_plan(client, admin_headers, code=internal_code, audience="internal")

    catalog = await client.get("/api/v1/catalog/plans")

    assert catalog.status_code == 200, catalog.text
    codes = {item["code"] for item in catalog.json()}
    assert public_code in codes
    assert internal_code not in codes
    assert public_plan["status"] == "published"
    assert public_plan["version"] == 1


async def test_future_scheduled_plan_is_hidden_until_effective_time(client: AsyncClient):
    admin_headers = await _login(client, role="admin")
    code = f"SCHEDULED_{uuid.uuid4().hex[:8].upper()}"
    created = await client.post(
        "/api/admin/v1/plans",
        headers=admin_headers,
        json=_annual_plan_payload(code),
    )
    scheduled = await client.post(
        f"/api/admin/v1/plans/{created.json()['id']}/publish",
        headers=admin_headers,
        json={"effectiveAt": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
    )
    catalog = await client.get("/api/v1/catalog/plans")

    assert scheduled.status_code == 200, scheduled.text
    assert scheduled.json()["status"] == "scheduled"
    assert code not in {item["code"] for item in catalog.json()}


async def test_published_plan_cannot_be_rescheduled_without_clone(client: AsyncClient):
    admin_headers = await _login(client, role="admin")
    plan = await _create_and_publish_plan(
        client,
        admin_headers,
        code=f"LOCKED_{uuid.uuid4().hex[:8].upper()}",
    )

    response = await client.post(
        f"/api/admin/v1/plans/{plan['id']}/publish",
        headers=admin_headers,
        json={"effectiveAt": (datetime.now(UTC) + timedelta(days=2)).isoformat()},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PLAN_VERSION_LOCKED"


async def test_due_scheduled_plan_is_promoted_and_previous_version_retired(client: AsyncClient):
    admin_headers = await _login(client, role="admin")
    original = await _create_and_publish_plan(
        client,
        admin_headers,
        code=f"ROLLOVER_{uuid.uuid4().hex[:8].upper()}",
    )
    clone = await client.post(f"/api/admin/v1/plans/{original['id']}/clone", headers=admin_headers)
    scheduled = await client.post(
        f"/api/admin/v1/plans/{clone.json()['id']}/publish",
        headers=admin_headers,
        json={"effectiveAt": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
    )
    assert scheduled.json()["status"] == "scheduled"

    from sqlalchemy import update

    from app.modules.catalog.models import PlanSkuVersion

    async with SessionLocal() as db:
        await db.execute(
            update(PlanSkuVersion)
            .where(PlanSkuVersion.id == scheduled.json()["id"])
            .values(effective_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await db.commit()

    await client.get("/api/v1/catalog/plans")
    versions = await client.get("/api/admin/v1/plans", headers=admin_headers)
    statuses = {item["id"]: item["status"] for item in versions.json()}

    assert statuses[original["id"]] == "retired"
    assert statuses[scheduled.json()["id"]] == "published"


async def test_module_price_publish_and_quote(client: AsyncClient):
    admin_headers = await _login(client, role="admin")
    user_headers = await _login(client, role="user")
    version_name = f"price-{uuid.uuid4().hex[:8]}"
    created = await client.post(
        "/api/admin/v1/price-versions",
        headers=admin_headers,
        json={"version": version_name},
    )
    assert created.status_code == 201, created.text
    version_id = created.json()["id"]

    tts = await client.put(
        f"/api/admin/v1/price-versions/{version_id}/modules/tts",
        headers=admin_headers,
        json={
            "displayName": "TTS 文本生成语音",
            "billingUnit": "per_1k_chars",
            "unitSize": 1000,
            "pointsPerUnit": 10,
            "minimumPoints": 10,
            "enabled": True,
            "publicDescription": "每 1000 字 10 积分",
            "internalCostCentsPerUnit": 250,
            "targetMarginBps": 6000,
        },
    )
    assert tts.status_code == 200, tts.text
    avatar = await client.put(
        f"/api/admin/v1/price-versions/{version_id}/modules/digital_human",
        headers=admin_headers,
        json={
            "displayName": "数字人视频",
            "billingUnit": "per_second",
            "unitSize": 1,
            "pointsPerUnit": 2,
            "minimumPoints": 2,
            "enabled": True,
            "publicDescription": "每秒 2 积分",
            "internalCostCentsPerUnit": 20,
            "targetMarginBps": 6000,
        },
    )
    assert avatar.status_code == 200, avatar.text

    published = await client.post(
        f"/api/admin/v1/price-versions/{version_id}/publish",
        headers=admin_headers,
    )
    assert published.status_code == 200, published.text

    prices = await client.get("/api/v1/catalog/module-prices")
    assert prices.status_code == 200, prices.text
    assert prices.json()["version"] == version_name
    assert {item["module"] for item in prices.json()["items"]} == {"tts", "digital_human"}
    assert all("internalCostCentsPerUnit" not in item for item in prices.json()["items"])

    anonymous_quote = await client.post(
        "/api/v1/billing/price-preview",
        json={
            "items": [
                {"module": "tts", "quantity": 1800},
                {"module": "digital_human", "quantity": 120},
            ]
        },
    )
    assert anonymous_quote.status_code == 401

    quote = await client.post(
        "/api/v1/billing/price-preview",
        headers=user_headers,
        json={
            "items": [
                {"module": "tts", "quantity": 1800},
                {"module": "digital_human", "quantity": 120},
            ]
        },
    )
    assert quote.status_code == 200, quote.text
    body = quote.json()
    assert body["priceVersion"] == version_name
    assert body["estimatedPoints"] == 260
    assert body["availablePoints"] == 0
    assert body["expiresAt"]


async def test_future_price_version_does_not_replace_current_catalog_early(client: AsyncClient):
    admin_headers = await _login(client, role="admin")

    async def create_price_version(name: str, points: int, effective_at: str | None = None) -> dict:
        created = await client.post(
            "/api/admin/v1/price-versions",
            headers=admin_headers,
            json={"version": name},
        )
        version_id = created.json()["id"]
        await client.put(
            f"/api/admin/v1/price-versions/{version_id}/modules/tts",
            headers=admin_headers,
            json={
                "displayName": "TTS",
                "billingUnit": "per_1k_chars",
                "unitSize": 1000,
                "pointsPerUnit": points,
                "minimumPoints": points,
                "enabled": True,
            },
        )
        payload = {"effectiveAt": effective_at} if effective_at else None
        published = await client.post(
            f"/api/admin/v1/price-versions/{version_id}/publish",
            headers=admin_headers,
            json=payload,
        )
        return published.json()

    current_name = f"current-{uuid.uuid4().hex[:8]}"
    future_name = f"future-{uuid.uuid4().hex[:8]}"
    await create_price_version(current_name, 10)
    scheduled = await create_price_version(
        future_name,
        99,
        (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    )

    catalog = await client.get("/api/v1/catalog/module-prices")
    assert scheduled["status"] == "scheduled"
    assert catalog.json()["version"] == current_name

    from sqlalchemy import update

    from app.modules.catalog.models import PriceCatalogVersion

    async with SessionLocal() as db:
        await db.execute(
            update(PriceCatalogVersion)
            .where(PriceCatalogVersion.id == scheduled["id"])
            .values(effective_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await db.commit()

    promoted_catalog = await client.get("/api/v1/catalog/module-prices")
    versions = await client.get("/api/admin/v1/price-versions", headers=admin_headers)
    statuses = {item["version"]: item["status"] for item in versions.json()}
    assert promoted_catalog.json()["version"] == future_name
    assert statuses[current_name] == "retired"
    assert statuses[future_name] == "published"


async def test_quote_reservation_freezes_and_idempotently_releases_points(client: AsyncClient):
    admin_headers = await _login(client, role="admin")
    user_headers = await _login(client, role="user")
    version_name = f"reserve-{uuid.uuid4().hex[:8]}"
    created = await client.post(
        "/api/admin/v1/price-versions",
        headers=admin_headers,
        json={"version": version_name},
    )
    version_id = created.json()["id"]
    configured = await client.put(
        f"/api/admin/v1/price-versions/{version_id}/modules/tts",
        headers=admin_headers,
        json={
            "displayName": "TTS",
            "billingUnit": "per_1k_chars",
            "unitSize": 1000,
            "pointsPerUnit": 10,
            "minimumPoints": 10,
            "enabled": True,
        },
    )
    assert configured.status_code == 200, configured.text
    await client.post(f"/api/admin/v1/price-versions/{version_id}/publish", headers=admin_headers)

    from app.modules.billing.service import grant_points

    token = user_headers["Authorization"].removeprefix("Bearer ")
    user_id = str(decode_token(token)["sub"])
    async with SessionLocal() as db:
        await grant_points(
            db,
            user_id,
            500,
            source_type="manual",
            source_id=f"test-{uuid.uuid4().hex}",
            expires_at=datetime.now(UTC) + timedelta(days=30),
            commit=True,
        )

    quote = await client.post(
        "/api/v1/billing/price-preview",
        headers=user_headers,
        json={"items": [{"module": "tts", "quantity": 1800}]},
    )
    assert quote.status_code == 200, quote.text
    quote_id = quote.json()["quoteId"]

    reserved = await client.post(
        "/api/v1/billing/reservations",
        headers=user_headers,
        json={"quoteId": quote_id, "count": 1},
    )
    assert reserved.status_code == 201, reserved.text
    reservation_id = reserved.json()["items"][0]["id"]
    assert reserved.json()["availablePoints"] == 480

    duplicate = await client.post(
        "/api/v1/billing/reservations",
        headers=user_headers,
        json={"quoteId": quote_id, "count": 1},
    )
    assert duplicate.status_code == 409

    released = await client.post(
        f"/api/v1/billing/reservations/{reservation_id}/release",
        headers=user_headers,
    )
    repeated = await client.post(
        f"/api/v1/billing/reservations/{reservation_id}/release",
        headers=user_headers,
    )
    assert released.status_code == 200, released.text
    assert repeated.status_code == 200, repeated.text
    assert released.json()["availablePoints"] == 500
    assert repeated.json()["availablePoints"] == 500


async def test_admin_reservation_is_zero_cost_and_does_not_write_billing_usage(client: AsyncClient):
    admin_tokens = await _user_login_for_role(client, role="admin")
    admin_headers = {"Authorization": f"Bearer {admin_tokens['accessToken']}"}
    admin_id = str(decode_token(admin_tokens["accessToken"])["sub"])

    quote = await client.post(
        "/api/v1/billing/price-preview",
        headers=admin_headers,
        json={"items": [{"module": "tts", "quantity": 1}]},
    )
    assert quote.status_code == 200, quote.text

    reserved = await client.post(
        "/api/v1/billing/reservations",
        headers=admin_headers,
        json={"quoteId": quote.json()["quoteId"]},
    )
    assert reserved.status_code == 201, reserved.text
    reservation_id = reserved.json()["items"][0]["id"]
    assert reserved.json()["items"][0]["reservedPoints"] == 0

    from sqlalchemy import func, select

    from app.modules.billing.models import (
        CreditLedger,
        CreditReservation,
        QuotaAccount,
        QuotaUsage,
    )
    from app.modules.billing.service import settle_reservation

    async with SessionLocal() as db:
        reservation = await db.get(CreditReservation, reservation_id)
        assert reservation is not None and reservation.reserved_points == 0
        assert await settle_reservation(db, reservation_id, "admin-task") == 1
        account_count = await db.scalar(select(func.count(QuotaAccount.id)).where(QuotaAccount.user_id == admin_id))
        ledger_count = await db.scalar(select(func.count(CreditLedger.id)).where(CreditLedger.user_id == admin_id))
        usage_count = await db.scalar(select(func.count(QuotaUsage.id)).where(QuotaUsage.user_id == admin_id))

    assert account_count == 0
    assert ledger_count == 0
    assert usage_count == 0


async def test_same_quote_can_only_be_reserved_once_under_concurrency(client: AsyncClient):
    admin_headers = await _login(client, role="admin")
    user_headers = await _login(client, role="user")
    version = await client.post(
        "/api/admin/v1/price-versions",
        headers=admin_headers,
        json={"version": f"concurrent-{uuid.uuid4().hex[:8]}"},
    )
    version_id = version.json()["id"]
    await client.put(
        f"/api/admin/v1/price-versions/{version_id}/modules/tts",
        headers=admin_headers,
        json={
            "displayName": "TTS",
            "billingUnit": "per_action",
            "unitSize": 1,
            "pointsPerUnit": 10,
            "minimumPoints": 10,
            "enabled": True,
        },
    )
    await client.post(f"/api/admin/v1/price-versions/{version_id}/publish", headers=admin_headers)

    from app.modules.billing.service import grant_points

    user_id = str(decode_token(user_headers["Authorization"].removeprefix("Bearer "))["sub"])
    async with SessionLocal() as db:
        await grant_points(
            db,
            user_id,
            100,
            source_type="manual",
            source_id=f"test-{uuid.uuid4().hex}",
            expires_at=datetime.now(UTC) + timedelta(days=30),
            commit=True,
        )
    quote = await client.post(
        "/api/v1/billing/price-preview",
        headers=user_headers,
        json={"items": [{"module": "tts", "quantity": 1}]},
    )

    async def reserve():
        return await client.post(
            "/api/v1/billing/reservations",
            headers=user_headers,
            json={"quoteId": quote.json()["quoteId"]},
        )

    responses = await asyncio.gather(reserve(), reserve())

    assert sorted(response.status_code for response in responses) == [201, 409]
    balance = await client.get("/api/v1/billing/balance", headers=user_headers)
    assert balance.json()["balance"] == 90


async def test_reservation_consumes_earliest_expiring_grant_and_release_restores_it(client: AsyncClient):
    admin_headers = await _login(client, role="admin")
    user_headers = await _login(client, role="user")
    version = await client.post(
        "/api/admin/v1/price-versions",
        headers=admin_headers,
        json={"version": f"grant-order-{uuid.uuid4().hex[:8]}"},
    )
    version_id = version.json()["id"]
    await client.put(
        f"/api/admin/v1/price-versions/{version_id}/modules/tts",
        headers=admin_headers,
        json={
            "displayName": "TTS",
            "billingUnit": "per_action",
            "unitSize": 1,
            "pointsPerUnit": 15,
            "minimumPoints": 15,
            "enabled": True,
        },
    )
    await client.post(f"/api/admin/v1/price-versions/{version_id}/publish", headers=admin_headers)

    from sqlalchemy import select

    from app.modules.billing.models import CreditGrant
    from app.modules.billing.service import grant_points

    user_id = str(decode_token(user_headers["Authorization"].removeprefix("Bearer "))["sub"])
    first_source = f"first-{uuid.uuid4().hex}"
    second_source = f"second-{uuid.uuid4().hex}"
    async with SessionLocal() as db:
        await grant_points(
            db,
            user_id,
            10,
            source_type="plan",
            source_id=first_source,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        await grant_points(
            db,
            user_id,
            20,
            source_type="points_pack",
            source_id=second_source,
            expires_at=datetime.now(UTC) + timedelta(days=30),
            commit=True,
        )

    quote = await client.post(
        "/api/v1/billing/price-preview",
        headers=user_headers,
        json={"items": [{"module": "tts", "quantity": 1}]},
    )
    reserved = await client.post(
        "/api/v1/billing/reservations",
        headers=user_headers,
        json={"quoteId": quote.json()["quoteId"]},
    )
    assert reserved.status_code == 201, reserved.text
    reservation_id = reserved.json()["items"][0]["id"]

    async with SessionLocal() as db:
        grants = {
            item.source_id: item.remaining_points
            for item in (
                await db.execute(select(CreditGrant).where(CreditGrant.source_id.in_([first_source, second_source])))
            )
            .scalars()
            .all()
        }
    assert grants == {first_source: 0, second_source: 15}

    released = await client.post(
        f"/api/v1/billing/reservations/{reservation_id}/release",
        headers=user_headers,
    )
    assert released.status_code == 200, released.text
    async with SessionLocal() as db:
        restored = {
            item.source_id: item.remaining_points
            for item in (
                await db.execute(select(CreditGrant).where(CreditGrant.source_id.in_([first_source, second_source])))
            )
            .scalars()
            .all()
        }
    assert restored == {first_source: 10, second_source: 20}


async def test_pipeline_attaches_quote_reservation_and_cancel_releases_it(client: AsyncClient):
    admin_headers = await _login(client, role="admin")
    user_headers = await _login(client, role="user")
    version = await client.post(
        "/api/admin/v1/price-versions",
        headers=admin_headers,
        json={"version": f"pipeline-{uuid.uuid4().hex[:8]}"},
    )
    version_id = version.json()["id"]
    # 已带确认文案的任务跳过 rewrite 步，报价不含 script_generation
    for module in ("tts", "digital_human", "hd_export"):
        configured = await client.put(
            f"/api/admin/v1/price-versions/{version_id}/modules/{module}",
            headers=admin_headers,
            json={
                "displayName": module,
                "billingUnit": "per_action",
                "unitSize": 1,
                "pointsPerUnit": 10,
                "minimumPoints": 10,
                "enabled": True,
            },
        )
        assert configured.status_code == 200, configured.text
    await client.post(f"/api/admin/v1/price-versions/{version_id}/publish", headers=admin_headers)

    from app.modules.billing.service import grant_points

    token = user_headers["Authorization"].removeprefix("Bearer ")
    user_id = str(decode_token(token)["sub"])
    async with SessionLocal() as db:
        await grant_points(
            db,
            user_id,
            100,
            source_type="manual",
            source_id=f"test-{uuid.uuid4().hex}",
            expires_at=datetime.now(UTC) + timedelta(days=30),
            commit=True,
        )

    quote = await client.post(
        "/api/v1/billing/price-preview",
        headers=user_headers,
        json={
            "items": [
                {"module": "tts", "quantity": 1},
                {"module": "digital_human", "quantity": 1},
                {"module": "hd_export", "quantity": 1},
            ]
        },
    )
    created = await client.post(
        "/api/v1/pipelines",
        headers=user_headers,
        json={
            "ipId": user_id,
            "scriptText": "这是一段足够长的测试口播文案，用于验证积分冻结和取消释放。",
            "mode": "manual",
            "count": 1,
            "quoteId": quote.json()["quoteId"],
        },
    )
    assert created.status_code == 200, created.text
    task_id = created.json()[0]["id"]

    from sqlalchemy import select

    from app.modules.pipeline.models import PipelineTask

    async with SessionLocal() as db:
        task = (await db.execute(select(PipelineTask).where(PipelineTask.id == task_id))).scalar_one()
        assert task.reservation_id

    canceled = await client.post(f"/api/v1/pipelines/{task_id}/cancel", headers=user_headers)
    assert canceled.status_code == 200, canceled.text
    balance = await client.get("/api/v1/billing/balance", headers=user_headers)
    assert balance.json()["balance"] == 100


async def test_pipeline_rejects_quote_that_does_not_cover_task_modules(client: AsyncClient):
    admin_headers = await _login(client, role="admin")
    user_headers = await _login(client, role="user")
    user_id = str(decode_token(user_headers["Authorization"].removeprefix("Bearer "))["sub"])
    version = await client.post(
        "/api/admin/v1/price-versions",
        headers=admin_headers,
        json={"version": f"underquote-{uuid.uuid4().hex[:8]}"},
    )
    version_id = version.json()["id"]
    for module in ("script_generation", "tts", "digital_human", "hd_export"):
        await client.put(
            f"/api/admin/v1/price-versions/{version_id}/modules/{module}",
            headers=admin_headers,
            json={
                "displayName": module,
                "billingUnit": "per_action",
                "unitSize": 1,
                "pointsPerUnit": 10,
                "minimumPoints": 10,
                "enabled": True,
            },
        )
    await client.post(f"/api/admin/v1/price-versions/{version_id}/publish", headers=admin_headers)

    quote = await client.post(
        "/api/v1/billing/price-preview",
        headers=user_headers,
        json={"items": [{"module": "tts", "quantity": 1}]},
    )
    created = await client.post(
        "/api/v1/pipelines",
        headers=user_headers,
        json={
            "ipId": user_id,
            "scriptText": "这是一段足够长的口播文案，不能只使用单个低价模块报价。",
            "mode": "manual",
            "quoteId": quote.json()["quoteId"],
        },
    )

    assert created.status_code == 409
    assert created.json()["detail"]["code"] == "QUOTE_TASK_MISMATCH"


async def test_pipeline_rejects_one_second_quote_for_source_task(client: AsyncClient):
    admin_headers = await _login(client, role="admin")
    user_headers = await _login(client, role="user")
    user_id = str(decode_token(user_headers["Authorization"].removeprefix("Bearer "))["sub"])
    version = await client.post(
        "/api/admin/v1/price-versions",
        headers=admin_headers,
        json={"version": f"source-underquote-{uuid.uuid4().hex[:8]}"},
    )
    version_id = version.json()["id"]
    units = {
        "asr": "per_second",
        "script_generation": "per_1k_chars",
        "tts": "per_1k_chars",
        "digital_human": "per_second",
        "hd_export": "per_action",
    }
    for module, billing_unit in units.items():
        await client.put(
            f"/api/admin/v1/price-versions/{version_id}/modules/{module}",
            headers=admin_headers,
            json={
                "displayName": module,
                "billingUnit": billing_unit,
                "unitSize": 1 if billing_unit in {"per_second", "per_action"} else 1000,
                "pointsPerUnit": 1,
                "minimumPoints": 1,
                "enabled": True,
            },
        )
    await client.post(f"/api/admin/v1/price-versions/{version_id}/publish", headers=admin_headers)

    quote = await client.post(
        "/api/v1/billing/price-preview",
        headers=user_headers,
        json={"items": [{"module": module, "quantity": 1} for module in units]},
    )
    created = await client.post(
        "/api/v1/pipelines",
        headers=user_headers,
        json={
            "ipId": user_id,
            "sourceUrl": "https://example.com/source-video",
            "mode": "manual",
            "quoteId": quote.json()["quoteId"],
        },
    )

    assert created.status_code == 409
    assert created.json()["detail"]["code"] == "QUOTE_TASK_MISMATCH"


async def test_disabled_douyidou_is_skipped_in_direct_and_fallback_parse(client: AsyncClient, monkeypatch):
    from app.modules.content import service as content_service
    from app.providers.douyidou import DouyidouParser
    from app.providers.mock import MockASR, MockParser
    from app.providers.registry import registry

    async def provider_enabled(provider_name: str) -> bool:
        return provider_name != "douyidou"

    async def forbidden_call(*_args, **_kwargs):
        raise AssertionError("disabled Douyidou provider was called")

    monkeypatch.setattr(registry, "provider_enabled", provider_enabled)
    monkeypatch.setattr(DouyidouParser, "parse_url_full", forbidden_call)
    monkeypatch.setattr(registry, "parse_chain", [DouyidouParser(), MockParser()])
    monkeypatch.setattr(registry, "asr_chain", [MockASR()])

    user_headers = await _login(client, role="user")
    user_id = str(decode_token(user_headers["Authorization"].removeprefix("Bearer "))["sub"])
    async with SessionLocal() as db:
        # 新契约：douyidou 被禁用时不得调用（forbidden_call 兼验）；降级链落到 Mock 占位视频时
        # 不再产出假转写，而是返回可操作降级提示
        with pytest.raises(HTTPException) as exc_info:
            await content_service.parse_url(
                db,
                user_id,
                "https://www.douyin.com/video/123",
                None,
            )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "LINK_SOURCE_UNAVAILABLE"


async def test_time_priced_url_asr_rejects_missing_exact_duration(monkeypatch: pytest.MonkeyPatch):
    from app.modules.content import service as content_service
    from app.providers.douyidou import DouyidouParser, DouyidouParseResult
    from app.providers.registry import registry

    async def provider_enabled(_provider_name: str) -> bool:
        return True

    async def parsed_without_duration(*_args, **_kwargs) -> DouyidouParseResult:
        return DouyidouParseResult(
            platform="douyin",
            title="无可信时长",
            video_url="https://example.com/media.mp4",
        )

    async def duration_unavailable(*_args, **_kwargs):
        return None

    monkeypatch.setattr(registry, "provider_enabled", provider_enabled)
    monkeypatch.setattr(DouyidouParser, "parse_url_full", parsed_without_duration)
    monkeypatch.setattr(content_service, "probe_duration", duration_unavailable)

    with pytest.raises(HTTPException) as exc:
        await content_service.parse_url(
            None,  # type: ignore[arg-type]
            "user-test",
            "https://www.douyin.com/video/123",
            None,
            verified_duration_seconds=None,
            require_verified_duration=True,
        )

    assert exc.value.detail["code"] == "MEDIA_DURATION_UNVERIFIED"


async def test_production_engine_rejects_legacy_task_without_reservation(client: AsyncClient, monkeypatch):
    from app.modules.pipeline import engine
    from app.modules.pipeline.models import PipelineTask

    task = PipelineTask(
        user_id=uuid.uuid4().hex,
        ip_id="test-ip",
        title="旧任务",
        script_text="不得绕过积分冻结",
        mode="auto",
        steps_json="[]",
    )
    async with SessionLocal() as db:
        db.add(task)
        await db.commit()
        task_id = task.id

    monkeypatch.setattr(engine.settings, "app_env", "prod")
    await engine.run_task(task_id)

    async with SessionLocal() as db:
        rejected = await db.get(PipelineTask, task_id)
    assert rejected is not None
    assert rejected.status == "failed"
    assert rejected.error == "billing: reservation required"


async def test_plan_concurrency_is_enforced_for_parallel_creates(client: AsyncClient):
    admin_headers = await _login(client, role="admin")
    user_headers = await _login(client, role="user")
    plan = await _create_and_publish_plan(
        client,
        admin_headers,
        code=f"CONCURRENCY_{uuid.uuid4().hex[:8].upper()}",
    )

    from app.modules.activation.models import UserSubscription
    from app.modules.billing.service import grant_points
    from app.modules.catalog.models import PlanSkuVersion

    user_id = str(decode_token(user_headers["Authorization"].removeprefix("Bearer "))["sub"])
    async with SessionLocal() as db:
        version = await db.get(PlanSkuVersion, plan["id"])
        assert version is not None
        version.max_concurrency = 1
        db.add(
            UserSubscription(
                user_id=user_id,
                code_id=f"test-{uuid.uuid4().hex}",
                plan_type="annual_bundle",
                sku_version_id=plan["id"],
                plan_sku_code=plan["code"],
                duration_days=365,
                expires_at=datetime.now(UTC) + timedelta(days=365),
            )
        )
        await grant_points(
            db,
            user_id,
            100,
            source_type="manual",
            source_id=f"test-{uuid.uuid4().hex}",
            expires_at=datetime.now(UTC) + timedelta(days=30),
            commit=True,
        )

    price_version = await client.post(
        "/api/admin/v1/price-versions",
        headers=admin_headers,
        json={"version": f"concurrency-plan-{uuid.uuid4().hex[:8]}"},
    )
    price_version_id = price_version.json()["id"]
    # 带文案任务不含 script_generation，与服务端报价合同保持一致
    modules = ("tts", "digital_human", "hd_export")
    for module in modules:
        await client.put(
            f"/api/admin/v1/price-versions/{price_version_id}/modules/{module}",
            headers=admin_headers,
            json={
                "displayName": module,
                "billingUnit": "per_action",
                "unitSize": 1,
                "pointsPerUnit": 1,
                "minimumPoints": 1,
                "enabled": True,
            },
        )
    await client.post(
        f"/api/admin/v1/price-versions/{price_version_id}/publish",
        headers=admin_headers,
    )

    async def quote_id() -> str:
        response = await client.post(
            "/api/v1/billing/price-preview",
            headers=user_headers,
            json={"items": [{"module": module, "quantity": 1} for module in modules]},
        )
        return str(response.json()["quoteId"])

    first_quote, second_quote = await asyncio.gather(quote_id(), quote_id())

    async def create(quote: str):
        return await client.post(
            "/api/v1/pipelines",
            headers=user_headers,
            json={
                "ipId": user_id,
                "scriptText": "并发限制测试文案",
                "mode": "manual",
                "quoteId": quote,
            },
        )

    responses = await asyncio.gather(create(first_quote), create(second_quote))

    assert sorted(response.status_code for response in responses) == [200, 409]
    rejected = next(response for response in responses if response.status_code == 409)
    assert rejected.json()["detail"]["code"] == "PLAN_CONCURRENCY_EXCEEDED"

    accepted = next(response for response in responses if response.status_code == 200)
    task_id = accepted.json()[0]["id"]
    from app.modules.billing.service import settle_reservation
    from app.modules.pipeline.models import PipelineTask

    async with SessionLocal() as db:
        task = await db.get(PipelineTask, task_id)
        assert task is not None and task.reservation_id
        assert await settle_reservation(db, task.reservation_id, task.id) == 3

    usage = await client.get("/api/v1/billing/usage", headers=user_headers)
    assert usage.status_code == 200
    assert usage.json()["items"][0]["points"] == 3
    assert usage.json()["items"][0]["step"] == "pipeline"


async def test_provider_secrets_are_admin_only_masked_and_encrypted(client: AsyncClient):
    admin_headers = await _login(client, role="admin")
    secret = f"sk-{uuid.uuid4().hex}"

    blocked = await client.put(
        "/api/admin/v1/providers",
        headers=admin_headers,
        json={"settings": {"deepseek_base_url": "https://attacker.example/v1"}},
    )
    assert blocked.status_code == 400

    saved = await client.put(
        "/api/admin/v1/providers",
        headers=admin_headers,
        json={
            "settings": {
                "deepseek_api_key": secret,
                "deepseek_base_url": "https://api.deepseek.com/v1",
            }
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["settings"]["deepseek_api_key"] == "configured"

    fetched = await client.get("/api/admin/v1/providers", headers=admin_headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["settings"]["deepseek_api_key"] == "configured"

    from sqlalchemy import select

    from app.modules.settings.models import ProviderConfig

    async with SessionLocal() as db:
        stored = (
            await db.execute(select(ProviderConfig.value).where(ProviderConfig.key == "deepseek_api_key"))
        ).scalar_one()
    assert stored != secret
    assert stored.startswith("enc:v1:")


async def test_provider_settings_reject_invalid_dashscope_routing(client: AsyncClient):
    admin_headers = await _login(client, role="admin")

    invalid_settings = [
        {"dashscope_region": "moon-base"},
        {"dashscope_workspace_id": "workspace/invalid"},
        {"asr_flash_threshold_sec": "0"},
        {"asr_model": "fun asr"},
        {"dashscope_enabled": "yes"},
    ]
    for settings in invalid_settings:
        response = await client.put(
            "/api/admin/v1/providers",
            headers=admin_headers,
            json={"settings": settings},
        )
        assert response.status_code == 400, settings

    valid = await client.put(
        "/api/admin/v1/providers",
        headers=admin_headers,
        json={
            "settings": {
                "dashscope_workspace_id": "workspace_123",
                "dashscope_region": "ap-southeast-1",
                "asr_model": "fun-asr",
                "asr_flash_model": "fun-asr-flash-2026-06-15",
                "asr_flash_threshold_sec": "180",
                "dashscope_enabled": "true",
            }
        },
    )
    assert valid.status_code == 200, valid.text


async def test_activation_batch_uses_published_sku_version(client: AsyncClient):
    admin_headers = await _login(client, role="admin")
    plan = await _create_and_publish_plan(
        client,
        admin_headers,
        code=f"ACTIVATE_{uuid.uuid4().hex[:8].upper()}",
    )

    batch = await client.post(
        "/api/admin/v1/activation/batches",
        headers=admin_headers,
        json={
            "name": "首批年包",
            "skuVersionId": plan["id"],
            "count": 1,
            "channel": "partner-a",
        },
    )
    assert batch.status_code == 201, batch.text
    code = batch.json()["codes"][0]

    from sqlalchemy import select

    from app.modules.activation.models import ActivationCode

    async with SessionLocal() as db:
        stored_code = (await db.execute(select(ActivationCode.code))).scalars().all()[-1]
    assert stored_code != code
    assert len(stored_code) == 64

    legacy_admin_list = await client.get("/api/v1/activation/admin/codes", headers=admin_headers)
    assert legacy_admin_list.status_code == 404

    # 激活码即账号：未使用码首次登录即开户
    logged_in = await code_login(client, code, fingerprint=f"fp-{uuid.uuid4().hex[:12]}.abcd1234")
    activated_user_id = str(decode_token(logged_in["accessToken"])["sub"])
    user_headers = {"Authorization": f"Bearer {logged_in['accessToken']}"}

    subscription_now = await client.get("/api/v1/activation/subscription", headers=user_headers)
    assert subscription_now.status_code == 200, subscription_now.text
    assert subscription_now.json()["planSkuCode"] == plan["code"]
    assert subscription_now.json()["quotaBalance"] == 1000

    from app.modules.billing.models import CreditGrant, CreditLedger

    async with SessionLocal() as db:
        grant = (await db.execute(select(CreditGrant).where(CreditGrant.user_id == activated_user_id))).scalar_one()
        ledger = (
            await db.execute(
                select(CreditLedger).where(
                    CreditLedger.user_id == activated_user_id,
                    CreditLedger.event_type == "grant",
                )
            )
        ).scalar_one()
    assert grant.source_type == "plan"
    assert grant.granted_points == 1000
    assert ledger.points_delta == 1000

    from sqlalchemy import update

    from app.modules.activation.models import UserSubscription

    async with SessionLocal() as db:
        await db.execute(
            update(UserSubscription)
            .where(UserSubscription.user_id == activated_user_id)
            .values(next_grant_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await db.commit()

    subscription = await client.get(
        "/api/v1/subscription",
        headers=user_headers,
    )
    assert subscription.status_code == 200, subscription.text
    assert subscription.json()["monthlyPoints"] == 1000
    assert subscription.json()["planName"] == "标准年包"
    assert subscription.json()["quotaBalance"] == 2000
    assert subscription.json()["nextGrantAt"]
