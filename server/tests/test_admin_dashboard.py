"""运营总览驾驶舱聚合接口的契约测试。"""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.modules.activation.models import ActivationCode, UserSubscription
from app.modules.auth.models import User
from app.modules.billing.models import CreditGrant, QuotaUsage
from app.modules.catalog.models import ModulePrice, PlanSkuVersion, PriceCatalogVersion
from app.modules.pipeline.models import PipelineTask
from app.modules.publish.models import PublishJob


async def _admin_headers(client: AsyncClient) -> dict[str, str]:
    phone = f"139{uuid.uuid4().hex[:8]}"
    password = "Test@12345"
    async with SessionLocal() as db:
        db.add(
            User(
                phone=phone,
                password_hash=hash_password(password),
                nickname="仪表盘管理员",
                avatar_char="仪",
                role="admin",
            )
        )
        await db.commit()
    response = await client.post("/api/admin/v1/auth/login", json={"phone": phone, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


async def test_dashboard_requires_admin_token(client: AsyncClient) -> None:
    anonymous = await client.get("/api/admin/v1/dashboard")
    assert anonymous.status_code == 401


async def test_dashboard_returns_aligned_series_and_seeded_metrics(client: AsyncClient) -> None:
    headers = await _admin_headers(client)
    now = datetime.now(UTC)
    user_id = uuid.uuid4().hex

    async with SessionLocal() as db:
        # 激活收入：订阅指向 19900 分的 SKU 版本
        sku_version = PlanSkuVersion(
            sku_id=uuid.uuid4().hex,
            code=f"sku-{uuid.uuid4().hex[:8]}",
            status="published",
            name="仪表盘年包",
            display_price_cents=19900,
        )
        db.add(sku_version)
        await db.flush()
        # 成本估算：published 价格版本里 tts 每积分成本 = 40 / 8 = 5 分
        # effective_at/published_at 设为当前，确保排序压过启动种子版本成为生效版本
        catalog_version = PriceCatalogVersion(
            version=f"dash-{uuid.uuid4().hex[:8]}",
            status="published",
            effective_at=now,
            published_at=now,
        )
        db.add(catalog_version)
        await db.flush()
        db.add(
            ModulePrice(
                catalog_version_id=catalog_version.id,
                module="tts",
                display_name="语音合成",
                billing_unit="per_action",
                points_per_unit=8,
                internal_cost_cents_per_unit=40,
            )
        )
        db.add(CreditGrant(user_id=user_id, source_type="activation", granted_points=100, remaining_points=100))
        db.add(
            QuotaUsage(
                user_id=user_id,
                trace_id=uuid.uuid4().hex,
                step="voice",
                points=8,
            )
        )
        db.add(
            ActivationCode(
                code=uuid.uuid4().hex,
                status="used",
                bound_user_id=user_id,
                activated_at=now,
            )
        )
        db.add(
            UserSubscription(
                user_id=user_id,
                code_id=uuid.uuid4().hex,
                plan_type="annual",
                sku_version_id=sku_version.id,
            )
        )
        db.add(PipelineTask(user_id=user_id, status="done"))
        db.add(PipelineTask(user_id=user_id, status="failed"))
        db.add(PublishJob(user_id=user_id, platform="douyin", status="success"))
        db.add(PublishJob(user_id=user_id, platform="douyin", status="failed"))
        await db.commit()

    response = await client.get("/api/admin/v1/dashboard?days=7", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["rangeDays"] == 7
    assert len(body["dates"]) == 7
    # 所有序列必须与日期轴等长，前端才能直接绑定 x 轴
    for group in ("users", "activation", "credits", "production", "publishing", "economics"):
        for series in body[group].values():
            assert len(series) == 7, f"{group} 序列长度与日期轴不一致"

    assert body["kpis"]["totalUsers"] >= 1
    assert body["users"]["cumulativeUsers"][-1] == body["kpis"]["totalUsers"]
    assert body["credits"]["granted"][-1] >= 100
    assert body["credits"]["consumed"][-1] >= 8
    assert body["activation"]["activated"][-1] >= 1
    assert body["production"]["tasksCreated"][-1] >= 2
    assert body["publishing"]["succeeded"][-1] >= 1
    assert body["publishing"]["failed"][-1] >= 1
    # 收入 = SKU 展示价；成本 = 8 积分 × 5 分/积分
    assert body["economics"]["revenueCents"][-1] >= 19900
    assert body["economics"]["costCents"][-1] >= 40
    assert body["kpis"]["revenueCentsWindow"] >= 19900
    assert body["kpis"]["publishSuccessRate"] is not None


async def test_dashboard_rejects_out_of_range_days(client: AsyncClient) -> None:
    headers = await _admin_headers(client)
    too_small = await client.get("/api/admin/v1/dashboard?days=1", headers=headers)
    too_large = await client.get("/api/admin/v1/dashboard?days=365", headers=headers)
    assert too_small.status_code == 422
    assert too_large.status_code == 422


async def test_dashboard_buckets_by_ops_timezone_day(client: AsyncClient) -> None:
    """8 天前的数据不应落入 7 天窗口。"""
    headers = await _admin_headers(client)
    async with SessionLocal() as db:
        db.add(
            CreditGrant(
                user_id=uuid.uuid4().hex,
                source_type="activation",
                granted_points=999_999,
                remaining_points=999_999,
                created_at=datetime.now(UTC) - timedelta(days=9),
            )
        )
        await db.commit()

    response = await client.get("/api/admin/v1/dashboard?days=7", headers=headers)
    assert response.status_code == 200
    assert sum(response.json()["credits"]["granted"]) < 999_999
