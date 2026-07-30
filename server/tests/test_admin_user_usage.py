"""测试后台管理员查看用户调用记录功能"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.modules.activation.models import ActivationCode
from app.modules.auth.models import User
from app.modules.billing.models import QuotaUsage
from tests.helpers import code_login


@pytest.fixture
async def admin_user(client: AsyncClient):
    """创建并登录管理员用户"""
    phone = f"138{uuid.uuid4().hex[:8]}"
    password = "Admin@12345"

    async with SessionLocal() as db:
        user = User(
            phone=phone,
            password_hash=hash_password(password),
            nickname="管理员",
            avatar_char="管",
            role="admin",
            plan_type="none",
            plan_expires_at=datetime.now(UTC) + timedelta(days=365),
        )
        db.add(user)
        await db.commit()
        user_id = user.id

    response = await client.post("/api/admin/v1/auth/login", json={"phone": phone, "password": password})
    assert response.status_code == 200
    return {"user_id": user_id, "headers": {"Authorization": f"Bearer {response.json()['accessToken']}"}}


@pytest.fixture
async def normal_user(client: AsyncClient):
    """创建并登录普通用户"""
    phone = f"139{uuid.uuid4().hex[:8]}"
    password = "User@12345"

    async with SessionLocal() as db:
        user = User(
            phone=phone,
            password_hash=hash_password(password),
            nickname="普通用户",
            avatar_char="用",
            role="user",
            plan_type="trial",
            plan_expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        db.add(user)
        await db.commit()
        user_id = user.id

    # 普通用户通过激活码登录
    raw = await bind_used_code(user_id)
    tokens = await code_login(client, raw)
    return {"user_id": user_id, "headers": {"Authorization": f"Bearer {tokens['accessToken']}"}}


async def bind_used_code(user_id: str) -> str:
    """为已存在用户补一张已使用码"""
    from datetime import UTC, datetime

    from app.modules.activation import code_generator

    raw = code_generator.generate_batch(1)[0]
    async with SessionLocal() as db:
        db.add(
            ActivationCode(
                code=code_generator.hash_code(raw),
                plan_type="trial",
                quota_amount=0,
                duration_days=30,
                status="used",
                bound_user_id=user_id,
                activated_at=datetime.now(UTC),
            )
        )
        await db.commit()
    return raw


@pytest.mark.asyncio
async def test_admin_get_user_usage_success(client: AsyncClient, admin_user):
    """管理员能成功查看指定用户的调用记录"""
    # 创建测试用户
    async with SessionLocal() as db:
        user = User(
            phone="13800138000",
            password_hash=hash_password("Test@12345"),
            nickname="测试用户",
            avatar_char="测",
            role="user",
            plan_type="trial",
            plan_expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        db.add(user)
        await db.commit()
        user_id = user.id

    # 创建激活码
    async with SessionLocal() as db:
        code = ActivationCode(
            code="TEST1234",
            plan_type="trial",
            quota_amount=0,
            duration_days=30,
            status="used",
            bound_user_id=user_id,
            activated_at=datetime.now(UTC),
        )
        db.add(code)
        await db.commit()

    # 创建一些调用记录
    async with SessionLocal() as db:
        usage1 = QuotaUsage(
            id="usage-1",
            user_id=user_id,
            trace_id="trace-1",
            task_id="task-1",
            step="tts",
            resolution="1080p",
            points=80,
            compute="cloud",
        )
        usage2 = QuotaUsage(
            id="usage-2",
            user_id=user_id,
            trace_id="trace-2",
            task_id="task-2",
            step="voice",
            resolution="1080p",
            points=120,
            compute="cloud",
        )
        db.add_all([usage1, usage2])
        await db.commit()

    # 管理员请求调用记录
    response = await client.get(
        f"/api/admin/v1/admin/usage?user_id={user_id}&page=1&pageSize=20", headers=admin_user["headers"]
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["page"] == 1
    assert data["pageSize"] == 20
    assert data["hasMore"] is False
    assert len(data["items"]) == 2

    # 验证返回的记录内容
    item = data["items"][0]
    assert item["step"] in ["tts", "voice"]
    assert item["points"] in [80, 120]
    assert "createdAt" in item


@pytest.mark.asyncio
async def test_admin_get_user_usage_with_step_filter(client: AsyncClient, admin_user):
    """管理员能按步骤筛选用户的调用记录"""
    # 创建测试用户
    async with SessionLocal() as db:
        user = User(
            phone="13800138001",
            password_hash=hash_password("Test@12345"),
            nickname="筛选测试用户",
            avatar_char="筛",
            role="user",
            plan_type="trial",
            plan_expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        db.add(user)
        await db.commit()
        user_id = user.id

    # 创建不同步骤的调用记录
    async with SessionLocal() as db:
        usage1 = QuotaUsage(
            id="usage-filter-1",
            user_id=user_id,
            trace_id="trace-f1",
            task_id="task-f1",
            step="tts",
            resolution="1080p",
            points=80,
            compute="cloud",
        )
        usage2 = QuotaUsage(
            id="usage-filter-2",
            user_id=user_id,
            trace_id="trace-f2",
            task_id="task-f2",
            step="voice",
            resolution="1080p",
            points=120,
            compute="cloud",
        )
        db.add_all([usage1, usage2])
        await db.commit()

    # 筛选 tts 步骤
    response = await client.get(f"/api/admin/v1/admin/usage?user_id={user_id}&step=tts", headers=admin_user["headers"])

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["step"] == "tts"


@pytest.mark.asyncio
async def test_admin_get_user_usage_pagination(client: AsyncClient, admin_user):
    """管理员能分页查询用户的调用记录"""
    # 创建测试用户
    async with SessionLocal() as db:
        user = User(
            phone="13800138002",
            password_hash=hash_password("Test@12345"),
            nickname="分页测试用户",
            avatar_char="分",
            role="user",
            plan_type="trial",
            plan_expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        db.add(user)
        await db.commit()
        user_id = user.id

    # 创建 30 条记录
    async with SessionLocal() as db:
        for i in range(30):
            usage = QuotaUsage(
                id=f"usage-page-{i}",
                user_id=user_id,
                trace_id=f"trace-p{i}",
                task_id=f"task-p{i}",
                step="tts",
                resolution="1080p",
                points=10,
                compute="cloud",
            )
            db.add(usage)
        await db.commit()

    # 第一页
    response = await client.get(
        f"/api/admin/v1/admin/usage?user_id={user_id}&page=1&pageSize=10", headers=admin_user["headers"]
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 30
    assert data["page"] == 1
    assert data["pageSize"] == 10
    assert data["hasMore"] is True
    assert len(data["items"]) == 10

    # 第二页
    response = await client.get(
        f"/api/admin/v1/admin/usage?user_id={user_id}&page=2&pageSize=10", headers=admin_user["headers"]
    )
    assert response.status_code == 200
    data = response.json()
    assert data["page"] == 2
    assert len(data["items"]) == 10

    # 第三页（最后）
    response = await client.get(
        f"/api/admin/v1/admin/usage?user_id={user_id}&page=3&pageSize=10", headers=admin_user["headers"]
    )
    assert response.status_code == 200
    data = response.json()
    assert data["hasMore"] is False


@pytest.mark.asyncio
async def test_admin_get_user_usage_user_not_found(client: AsyncClient, admin_user):
    """管理员查询不存在的用户时返回 404"""
    response = await client.get("/api/admin/v1/admin/usage?user_id=non-existent-user", headers=admin_user["headers"])
    assert response.status_code == 404
    data = response.json()
    assert data["detail"]["code"] == "USER_NOT_FOUND"


@pytest.mark.asyncio
async def test_admin_get_user_usage_unauthorized(client: AsyncClient, normal_user):
    """普通用户不能调用管理员接口"""
    # 创建目标用户
    async with SessionLocal() as db:
        target_user = User(
            phone="13800138003",
            password_hash=hash_password("Test@12345"),
            nickname="目标用户",
            avatar_char="目",
            role="user",
            plan_type="trial",
            plan_expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        db.add(target_user)
        await db.commit()
        target_user_id = target_user.id

    # 普通用户尝试访问
    response = await client.get(f"/api/admin/v1/admin/usage?user_id={target_user_id}", headers=normal_user["headers"])
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_export_user_usage_csv(client: AsyncClient, admin_user):
    """管理员能导出用户的 CSV 消费明细"""
    # 创建测试用户
    async with SessionLocal() as db:
        user = User(
            phone="13800138004",
            password_hash=hash_password("Test@12345"),
            nickname="CSV导出测试",
            avatar_char="导",
            role="user",
            plan_type="trial",
            plan_expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        db.add(user)
        await db.commit()
        user_id = user.id

    # 创建一些调用记录
    async with SessionLocal() as db:
        usage = QuotaUsage(
            id="csv-usage-1",
            user_id=user_id,
            trace_id="trace-csv-1",
            task_id="task-csv-1",
            step="tts",
            resolution="1080p",
            points=80,
            compute="cloud",
        )
        db.add(usage)
        await db.commit()

    # 导出 CSV
    response = await client.get(f"/api/admin/v1/admin/usage/export?user_id={user_id}", headers=admin_user["headers"])

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert "attachment" in response.headers["content-disposition"]

    # 验证 CSV 内容
    csv_content = response.text
    lines = csv_content.strip().split("\n")
    assert len(lines) == 2  # 1 header + 1 data row
    assert "时间" in lines[0]
    assert "tts" in lines[1]
    assert "80" in lines[1]


@pytest.mark.asyncio
async def test_usage_exports_reject_ranges_larger_than_31_days(
    client: AsyncClient,
    admin_user,
    normal_user,
):
    created_from = (datetime.now(UTC) - timedelta(days=40)).isoformat()
    created_to = datetime.now(UTC).isoformat()

    admin_response = await client.get(
        "/api/admin/v1/admin/usage/export",
        params={
            "user_id": normal_user["user_id"],
            "createdFrom": created_from,
            "createdTo": created_to,
        },
        headers=admin_user["headers"],
    )
    user_response = await client.get(
        "/api/v1/billing/usage",
        params={
            "export": "csv",
            "createdFrom": created_from,
            "createdTo": created_to,
        },
        headers=normal_user["headers"],
    )

    assert admin_response.status_code == 422
    assert admin_response.json()["detail"]["code"] == "EXPORT_WINDOW_TOO_LARGE"
    assert user_response.status_code == 422
    assert user_response.json()["detail"]["code"] == "EXPORT_WINDOW_TOO_LARGE"
