"""S3-14 gray-account enforcement and durable monitoring aggregates."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.db import SessionLocal
from app.core.security import create_access_token, hash_password
from app.modules.auth.models import User
from app.modules.im import repository as im_repo
from app.modules.im import service as im_service
from app.modules.im.models import IMConversation, IMGrayAccount, IMListenerState, IMMetricEvent
from app.modules.im.schemas import AutomationConsentIn, ListenerControlIn, MonitoringIncidentIn, SendMessageIn
from app.modules.publish import repository as publish_repo


async def test_listener_requires_gray_account_approval(client: AsyncClient) -> None:
    del client
    user_id, account_id = await _create_account()
    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as error:
            await im_service.start_listener(db, user_id, ListenerControlIn(accountId=account_id))
        await im_repo.approve_gray_account(db, account_id, approved_by="admin-test")
        started = await im_service.start_listener(db, user_id, ListenerControlIn(accountId=account_id))

    assert error.value.status_code == 403
    assert isinstance(error.value.detail, dict)
    assert error.value.detail["code"] == "IM_GRAY_NOT_APPROVED"
    assert started.status == "listening"


async def test_monitoring_summary_reports_stage_three_guardrails(client: AsyncClient) -> None:
    del client
    user_id, account_id = await _create_account()
    async with SessionLocal() as db:
        await db.execute(delete(IMMetricEvent))
        await db.execute(delete(IMGrayAccount))
        await db.commit()
        await im_repo.approve_gray_account(db, account_id, approved_by="admin-test")
        for kind in (
            "listener_connect_attempt",
            "listener_connect_attempt",
            "listener_connected",
            "listener_disconnected",
            "send_success",
            "send_success",
            "send_success",
            "send_failure",
            "quota_rejected",
            "moderation_blocked",
            "credential_expired",
            "risk_control_incident",
        ):
            await im_repo.record_metric_event(db, kind=kind, account_id=account_id, user_id=user_id)
        summary = await im_service.get_monitoring_summary(db, hours=24)

    assert summary.grayAccounts == 1
    assert summary.connectionAttempts == 2
    assert summary.connectionSuccessRate == 50.0
    assert summary.dropoutRate == 100.0
    assert summary.sendSuccessRate == 75.0
    assert summary.quotaRejected == 1
    assert summary.moderationBlocked == 1
    assert summary.credentialExpired == 1
    assert summary.ownershipRejected == 0
    assert summary.riskControlIncidents == 1


async def test_unknown_account_cannot_enter_gray_allowlist(client: AsyncClient) -> None:
    del client
    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as error:
            await im_service.approve_gray_account(db, "missing-account", "admin-test")

    assert error.value.status_code == 404


async def test_manual_send_cannot_bypass_gray_allowlist(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del client
    user_id, account_id = await _create_account()
    conversation = IMConversation(account_id=account_id, user_id=user_id, remote_uid="gray-send")
    async with SessionLocal() as db:
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)

    monkeypatch.setattr(
        im_service.registry,
        "im_driver",
        lambda _platform: (_ for _ in ()).throw(AssertionError("gray gate must stop provider")),
    )
    async with SessionLocal() as db:
        with pytest.raises(HTTPException) as error:
            await im_service.send_message(db, user_id, conversation.id, SendMessageIn(content="不得绕过"))

    assert error.value.status_code == 403
    assert isinstance(error.value.detail, dict)
    assert error.value.detail["code"] == "IM_GRAY_NOT_APPROVED"


async def test_listener_reconcile_skips_account_removed_from_gray(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del client
    user_id, account_id = await _create_account()
    async with SessionLocal() as db:
        db.add(IMListenerState(account_id=account_id, user_id=user_id, status="listening"))
        await db.commit()

    from app.core.config import get_settings
    from app.workers import im_listener

    started: list[tuple[str, str]] = []
    monkeypatch.setattr(get_settings(), "im_enabled", True)
    monkeypatch.setattr(im_listener, "start_listening", lambda account, user: started.append((account, user)))

    await im_listener.reconcile_listeners()

    assert (account_id, user_id) not in started


async def test_removing_gray_account_cancels_scheduled_reply_before_provider(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del client
    user_id, account_id = await _create_account()
    conversation = IMConversation(account_id=account_id, user_id=user_id, remote_uid="gray-removal")
    async with SessionLocal() as db:
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)
        await im_repo.approve_gray_account(db, account_id, approved_by="admin-test")
        await im_service.start_listener(db, user_id, ListenerControlIn(accountId=account_id))
        await im_service.authorize_automation(
            db,
            user_id,
            AutomationConsentIn(accountId=account_id, accepted=True, riskVersion="im-auto-reply-v1"),
        )
        await im_service.set_global_kill_switch(db, stopped=False)
        message = await im_repo.create_message(
            db,
            conversation_id=conversation.id,
            user_id=user_id,
            direction="out",
            msg_type=7,
            content='{"text":"不得越过灰度移除"}',
            auto_replied=True,
            send_status="scheduled",
        )
        assert await im_service.remove_gray_account(db, account_id) is True

    monkeypatch.setattr(
        im_service.registry,
        "im_driver",
        lambda _platform: (_ for _ in ()).throw(AssertionError("removed gray account must stop provider")),
    )
    await im_service.run_scheduled_reply(message.id)

    async with SessionLocal() as db:
        state = await im_repo.get_listener_state(db, account_id, user_id)
        consent = await im_repo.get_automation_consent(db, account_id, user_id)
        loaded = await im_repo.get_message_by_id(db, message.id)
        approved = await im_repo.is_gray_account_enabled(db, account_id, user_id)
        await im_service.set_global_kill_switch(db, stopped=True)

    assert approved is False
    assert state is not None and state.status == "disconnected"
    assert state.error_msg == "gray_approval_removed"
    assert consent is not None and consent.auto_reply_enabled is False
    assert loaded is not None and loaded.send_status == "canceled"
    assert loaded.send_error == "GrayApprovalRemoved"


async def test_new_admin_im_routes_reject_user_audience_and_accept_admin(client: AsyncClient) -> None:
    user_id, account_id = await _create_account()
    admin_id = await _create_user(role="admin")
    user_headers = {"Authorization": f"Bearer {create_access_token(user_id)}"}
    wrong_audience_headers = {"Authorization": f"Bearer {create_access_token(admin_id)}"}
    admin_headers = {"Authorization": f"Bearer {create_access_token(admin_id, audience='admin')}"}
    requests = (
        ("GET", "/api/admin/v1/im/gray/accounts", None),
        ("PUT", f"/api/admin/v1/im/gray/accounts/{account_id}", None),
        ("DELETE", f"/api/admin/v1/im/gray/accounts/{account_id}", None),
        ("GET", "/api/admin/v1/im/monitoring", None),
        ("POST", "/api/admin/v1/im/monitoring/incidents", {"accountId": account_id, "detail": "测试事件"}),
    )
    for method, path, body in requests:
        assert (await client.request(method, path, json=body)).status_code == 401
        assert (await client.request(method, path, headers=user_headers, json=body)).status_code == 403
        assert (await client.request(method, path, headers=wrong_audience_headers, json=body)).status_code == 403

    assert (await client.put(f"/api/admin/v1/im/gray/accounts/{account_id}", headers=admin_headers)).status_code == 200
    assert (await client.get("/api/admin/v1/im/gray/accounts", headers=admin_headers)).status_code == 200
    assert (await client.get("/api/admin/v1/im/monitoring", headers=admin_headers)).status_code == 200
    assert (
        await client.post(
            "/api/admin/v1/im/monitoring/incidents",
            headers=admin_headers,
            json={"accountId": account_id, "detail": "测试事件"},
        )
    ).status_code == 201
    assert (
        await client.delete(f"/api/admin/v1/im/gray/accounts/{account_id}", headers=admin_headers)
    ).status_code == 200


async def test_admin_can_record_risk_control_incident(client: AsyncClient) -> None:
    del client
    _user_id, account_id = await _create_account()
    async with SessionLocal() as db:
        before = await im_service.get_monitoring_summary(db, hours=24)
        await im_service.record_risk_control_incident(
            db,
            MonitoringIncidentIn(accountId=account_id, detail="平台风险提示"),
        )
        after = await im_service.get_monitoring_summary(db, hours=24)

    assert after.riskControlIncidents == before.riskControlIncidents + 1


async def test_metric_cleanup_removes_only_expired_events(client: AsyncClient) -> None:
    del client
    cutoff = datetime.now(UTC) - timedelta(days=90)
    expired = IMMetricEvent(kind="send_success", created_at=cutoff - timedelta(seconds=1))
    current = IMMetricEvent(kind="send_success", created_at=cutoff + timedelta(seconds=1))
    async with SessionLocal() as db:
        db.add_all([expired, current])
        await db.commit()
        deleted = await im_repo.cleanup_metric_events(db, cutoff=cutoff, batch_size=1)
        remaining = set((await db.execute(select(IMMetricEvent.id))).scalars().all())

    assert deleted == 1
    assert expired.id not in remaining
    assert current.id in remaining


async def test_monitoring_listener_counts_only_active_gray_accounts(client: AsyncClient) -> None:
    del client
    user_id, account_id = await _create_account()
    async with SessionLocal() as db:
        before = await im_service.get_monitoring_summary(db, hours=24)
        await im_repo.approve_gray_account(db, account_id, approved_by="admin-test")
        db.add(IMListenerState(account_id=account_id, user_id=user_id, status="listening"))
        await db.commit()
        active = await im_service.get_monitoring_summary(db, hours=24)
        account = await publish_repo.get_account(db, account_id, user_id)
        assert account is not None
        account.status = "expired"
        await db.commit()
        expired = await im_service.get_monitoring_summary(db, hours=24)

    assert active.grayAccounts == before.grayAccounts + 1
    assert active.listenerAccounts == before.listenerAccounts + 1
    assert active.listeningAccounts == before.listeningAccounts + 1
    assert expired.grayAccounts == before.grayAccounts
    assert expired.listenerAccounts == before.listenerAccounts
    assert expired.listeningAccounts == before.listeningAccounts


async def test_gray_account_cap_blocks_expansion(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    del client
    _first_user, first_account = await _create_account()
    _second_user, second_account = await _create_account()
    from app.core.config import get_settings

    async with SessionLocal() as db:
        current = await im_repo.gray_account_count(db)
        monkeypatch.setattr(get_settings(), "im_gray_max_accounts", current + 1)
        await im_service.approve_gray_account(db, first_account, "admin-test")
        with pytest.raises(HTTPException) as error:
            await im_service.approve_gray_account(db, second_account, "admin-test")

    assert error.value.status_code == 409
    assert isinstance(error.value.detail, dict)
    assert error.value.detail["code"] == "IM_GRAY_LIMIT_REACHED"


async def test_gray_account_cap_is_atomic_for_concurrent_admin_approvals(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del client
    _first_user, first_account = await _create_account()
    _second_user, second_account = await _create_account()
    from app.core.config import get_settings

    async with SessionLocal() as db:
        current = await im_repo.gray_account_count(db)
    monkeypatch.setattr(get_settings(), "im_gray_max_accounts", current + 1)

    original_count = im_repo.gray_account_count
    both_counted = asyncio.Event()
    count_calls = 0

    async def synchronized_count(db) -> int:
        nonlocal count_calls
        value = await original_count(db)
        count_calls += 1
        if count_calls == 2:
            both_counted.set()
        await asyncio.wait_for(both_counted.wait(), timeout=1)
        return value

    monkeypatch.setattr(im_repo, "gray_account_count", synchronized_count)

    async def approve(account_id: str) -> str:
        async with SessionLocal() as db:
            try:
                await im_service.approve_gray_account(db, account_id, "admin-test")
                return "approved"
            except HTTPException as error:
                assert isinstance(error.detail, dict)
                return str(error.detail["code"])

    results = await asyncio.gather(
        approve(first_account),
        approve(second_account),
        return_exceptions=True,
    )

    assert sorted(results, key=str) == ["IM_GRAY_LIMIT_REACHED", "approved"]
    async with SessionLocal() as db:
        assert await original_count(db) == current + 1


async def _create_account() -> tuple[str, str]:
    user_id = await _create_user(role="user")
    async with SessionLocal() as db:
        account = await publish_repo.create_account(
            db,
            user_id=user_id,
            platform="douyin",
            nickname="灰度账号",
            session_json='{"cookie_str":"sessionid=test"}',
        )
    return user_id, account.id


async def _create_user(*, role: str) -> str:
    user_id = uuid.uuid4().hex
    async with SessionLocal() as db:
        db.add(
            User(
                id=user_id,
                phone=f"130{uuid.uuid4().hex[:8]}",
                password_hash=hash_password("Test@12345"),
                nickname="灰度监控测试",
                role=role,
            )
        )
        await db.commit()
    return user_id
