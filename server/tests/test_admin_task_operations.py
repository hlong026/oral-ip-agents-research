"""管理端全局任务查询与受控恢复契约。"""

import json
import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select

from app.core.audit import AuditLog
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.billing.models import CreditReservation
from app.modules.pipeline.models import PipelineTask
from app.modules.publish.models import PublishJob


async def _admin_headers(client: AsyncClient) -> dict[str, str]:
    phone = f"138{uuid.uuid4().hex[:8]}"
    password = "Test@12345"
    async with SessionLocal() as db:
        db.add(
            User(
                phone=phone,
                password_hash=hash_password(password),
                nickname="任务管理员",
                avatar_char="任",
                role="admin",
            )
        )
        await db.commit()
    response = await client.post("/api/admin/v1/auth/login", json={"phone": phone, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


async def test_admin_tasks_support_operational_filters_and_failure_classification(client: AsyncClient) -> None:
    headers = await _admin_headers(client)
    user_id = uuid.uuid4().hex
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        db.add(
            User(
                id=user_id,
                phone=f"137{uuid.uuid4().hex[:8]}",
                password_hash=hash_password("Test@12345"),
                nickname="任务用户",
                avatar_char="用",
            )
        )
        db.add(
            PipelineTask(
                id="admin-filter-task",
                user_id=user_id,
                title="认证失败任务",
                status="failed",
                current_step="publish",
                error="账号 Cookie 已失效，请重新登录",
                steps_json=json.dumps(
                    [{"step": "publish", "status": "failed", "provider": "douyin"}],
                    ensure_ascii=False,
                ),
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            PipelineTask(
                id="admin-old-task",
                user_id=user_id,
                title="旧任务",
                status="done",
                current_step="compose",
                created_at=now - timedelta(days=30),
                updated_at=now - timedelta(days=30),
            )
        )
        await db.commit()

    response = await client.get(
        "/api/admin/v1/tasks",
        params={
            "userId": user_id,
            "status": "failed",
            "step": "publish",
            "provider": "douyin",
            "createdFrom": (now - timedelta(hours=1)).isoformat(),
            "createdTo": (now + timedelta(hours=1)).isoformat(),
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == "admin-filter-task"
    assert body["items"][0]["userId"] == user_id
    assert body["items"][0]["userNickname"] == "任务用户"
    assert body["items"][0]["provider"] == "douyin"
    assert body["items"][0]["failureClass"] == "account"
    assert body["items"][0]["traceId"]


async def test_admin_cancel_and_retry_reuse_state_machine_and_write_audit(client: AsyncClient, monkeypatch) -> None:
    from app.modules.pipeline import service as pipeline_service

    headers = await _admin_headers(client)
    user_id = uuid.uuid4().hex
    reservation_id = uuid.uuid4().hex
    async with SessionLocal() as db:
        db.add(
            User(
                id=user_id,
                phone=f"136{uuid.uuid4().hex[:8]}",
                password_hash=hash_password("Test@12345"),
                nickname="恢复用户",
                avatar_char="恢",
            )
        )
        db.add(
            PipelineTask(
                id="admin-cancel-task",
                user_id=user_id,
                title="待取消任务",
                status="pending",
                current_step="voice",
            )
        )
        db.add(
            PipelineTask(
                id="admin-retry-task",
                user_id=user_id,
                title="待重试任务",
                status="failed",
                current_step="voice",
                error="provider timeout",
                reservation_id=reservation_id,
                steps_json=json.dumps([{"step": "voice", "status": "failed", "progress": 0.5, "provider": "hifly"}]),
            )
        )
        db.add(
            CreditReservation(
                id=reservation_id,
                user_id=user_id,
                quote_id="admin-retry-quote",
                task_id="admin-retry-task",
                reserved_points=8,
                status="reserved",
            )
        )
        await db.commit()

    monkeypatch.setattr(pipeline_service, "schedule_run", lambda *_args, **_kwargs: "queue-admin-retry")

    canceled = await client.post(
        "/api/admin/v1/tasks/admin-cancel-task/cancel",
        json={"reason": "用户确认停止并释放占用资源"},
        headers=headers,
    )
    retried = await client.post(
        "/api/admin/v1/tasks/admin-retry-task/retry",
        json={"step": "voice", "reason": "上游服务恢复后人工重试"},
        headers=headers,
    )

    assert canceled.status_code == 200, canceled.text
    assert canceled.json()["status"] == "canceled"
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "pending"

    async with SessionLocal() as db:
        audits = (
            (
                await db.execute(
                    select(AuditLog).where(
                        AuditLog.event.in_(["admin_pipeline_canceled", "admin_pipeline_retried"]),
                        AuditLog.task_id.in_(["admin-cancel-task", "admin-retry-task"]),
                    )
                )
            )
            .scalars()
            .all()
        )
    assert {item.event for item in audits} == {"admin_pipeline_canceled", "admin_pipeline_retried"}
    assert all("reason=" in item.detail and f"target_user={user_id}" in item.detail for item in audits)


async def test_admin_retry_refuses_non_failed_or_unknown_outcome_tasks(client: AsyncClient) -> None:
    headers = await _admin_headers(client)
    user_id = uuid.uuid4().hex
    async with SessionLocal() as db:
        db.add(
            PipelineTask(
                id="admin-running-task",
                user_id=user_id,
                status="running",
                current_step="voice",
            )
        )
        db.add(
            PipelineTask(
                id="admin-reconcile-task",
                user_id=user_id,
                status="reconciliation_required",
                current_step="avatar",
            )
        )
        await db.commit()

    running = await client.post(
        "/api/admin/v1/tasks/admin-running-task/retry",
        json={"step": "voice", "reason": "不应执行的重试"},
        headers=headers,
    )
    unknown = await client.post(
        "/api/admin/v1/tasks/admin-reconcile-task/retry",
        json={"step": "avatar", "reason": "结果未知时不可重试"},
        headers=headers,
    )

    assert running.status_code == 409
    assert running.json()["detail"]["code"] == "ADMIN_RETRY_NOT_ALLOWED"
    assert unknown.status_code == 409
    assert unknown.json()["detail"]["code"] == "RECONCILIATION_REQUIRED"


async def test_admin_retry_preflight_returns_new_quote_when_reservation_is_missing(
    client: AsyncClient, monkeypatch
) -> None:
    from app.modules.pipeline import service as pipeline_service

    headers = await _admin_headers(client)
    user_id = uuid.uuid4().hex
    async with SessionLocal() as db:
        db.add(
            PipelineTask(
                id="admin-quote-task",
                user_id=user_id,
                status="failed",
                current_step="voice",
                error="provider timeout",
            )
        )
        await db.commit()

    called: list[tuple[str, str]] = []

    async def fake_retry_quote(_db, task_id: str, owner_id: str) -> dict:
        called.append((task_id, owner_id))
        return {
            "quoteId": "admin-new-quote",
            "estimatedPoints": 12,
            "availablePoints": 80,
        }

    monkeypatch.setattr(pipeline_service, "create_retry_quote", fake_retry_quote)

    response = await client.post(
        "/api/admin/v1/tasks/admin-quote-task/retry-quote",
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "required": True,
        "quote": {
            "quoteId": "admin-new-quote",
            "estimatedPoints": 12,
            "availablePoints": 80,
        },
    }
    assert called == [("admin-quote-task", user_id)]


async def test_admin_operations_health_separates_provider_publish_and_billing_risk(client: AsyncClient) -> None:
    headers = await _admin_headers(client)
    suffix = uuid.uuid4().hex[:8]
    user_id = uuid.uuid4().hex
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        db.add(
            PipelineTask(
                id=f"health-task-{suffix}",
                user_id=user_id,
                status="done",
                current_step="compose",
                steps_json=json.dumps(
                    [
                        {
                            "step": "compose",
                            "status": "done",
                            "progress": 1,
                            "provider": f"health-provider-{suffix}",
                        }
                    ]
                ),
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            PipelineTask(
                id=f"health-quota-task-{suffix}",
                user_id=user_id,
                status="failed",
                current_step="compose",
                steps_json=json.dumps(
                    [
                        {
                            "step": "compose",
                            "status": "failed",
                            "progress": 0,
                            "provider": f"health-provider-{suffix}",
                            "error": "HTTP 429 quota exceeded",
                        }
                    ]
                ),
                created_at=now,
                updated_at=now,
            )
        )
        db.add_all(
            [
                PublishJob(user_id=user_id, platform="douyin", status="success", retry_count="1"),
                PublishJob(
                    user_id=user_id,
                    platform="douyin",
                    status="failed",
                    error="cookie expired, please login again",
                ),
                PublishJob(user_id=user_id, platform="xiaohongshu", status="export_ready"),
                CreditReservation(
                    user_id=user_id,
                    quote_id=f"health-reserved-{suffix}",
                    reserved_points=8,
                    status="reserved",
                ),
                CreditReservation(
                    user_id=user_id,
                    quote_id=f"health-released-{suffix}",
                    reserved_points=8,
                    status="released",
                ),
            ]
        )
        await db.commit()

    response = await client.get("/api/admin/v1/operations/health?hours=24", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    provider = next(item for item in body["providers"] if item["provider"] == f"health-provider-{suffix}")
    assert provider["attempts"] == 2
    assert provider["successes"] == 1
    assert provider["failures"] == 1
    assert provider["quotaFailures"] == 1
    assert provider["quotaAlert"] is True
    assert body["publishing"]["succeeded"] >= 1
    assert body["publishing"]["failed"] >= 1
    assert body["publishing"]["manualFallback"] >= 1
    assert body["publishing"]["recovered"] >= 1
    assert body["publishing"]["failureClasses"]["account"] >= 1
    assert body["billing"]["reserved"] >= 1
    assert body["billing"]["released"] >= 1
