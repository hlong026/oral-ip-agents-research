"""套餐与价格目录业务逻辑。"""

import json
import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit

from . import repository as repo
from .models import ModulePrice, PlanSku, PlanSkuVersion, PriceCatalogVersion
from .schemas import BillingUnit, ModulePriceAdminOut, ModulePricePublicOut, PlanCreateIn, PlanOut

ALLOWED_MODULES = {
    "topic_generation",
    "script_generation",
    "asr",
    "tts",
    "voice_clone",
    "digital_human",
    "image_generation",
    "video_generation",
    "video_translation",
    "hd_export",
}

MODULE_BILLING_UNITS = {
    "topic_generation": {"per_action", "per_1k_chars", "per_1k_tokens"},
    "script_generation": {"per_action", "per_1k_chars", "per_1k_tokens"},
    "asr": {"per_action", "per_minute", "per_second"},
    "tts": {"per_action", "per_1k_chars", "per_1k_tokens"},
    "voice_clone": {"per_action", "per_asset"},
    "digital_human": {"per_action", "per_minute", "per_second", "per_asset"},
    "image_generation": {"per_action", "per_image"},
    "video_generation": {"per_action", "per_minute", "per_second", "per_asset"},
    "video_translation": {"per_action", "per_minute", "per_second"},
    "hd_export": {"per_action", "per_asset"},
}

# 迁移前流水线按步骤固定扣费。首个目录保持相同积分，避免部署后价格目录为空，
# 也避免存量用户在管理员首次配置前遭遇意外涨价。
LEGACY_MODULE_PRICES = [
    ("topic_generation", "AI 选题生成", "per_action", 1, "每次 1 积分"),
    ("asr", "ASR 音频转文字", "per_action", 2, "每次 2 积分"),
    ("script_generation", "AI 文案生成", "per_action", 2, "每次 2 积分"),
    ("tts", "TTS 文本生成语音", "per_action", 8, "每次 8 积分"),
    ("voice_clone", "声音克隆训练", "per_asset", 10, "每个声音 10 积分"),
    ("digital_human", "数字人视频生成", "per_action", 20, "每次 20 积分"),
    ("hd_export", "视频合成导出", "per_action", 3, "每次 3 积分"),
]


async def seed_initial_price_catalog(db: AsyncSession) -> None:
    """仅在全新价格目录中写入兼容旧扣费规则的首个已发布版本。"""
    count = await db.scalar(select(func.count(PriceCatalogVersion.id)))
    if count:
        return

    now = datetime.now(UTC)
    version = PriceCatalogVersion(
        version="legacy-v1",
        status="published",
        created_by="system",
        effective_at=now,
        published_at=now,
    )
    db.add(version)
    await db.flush()
    db.add_all(
        [
            ModulePrice(
                catalog_version_id=version.id,
                module=module,
                display_name=display_name,
                billing_unit=billing_unit,
                unit_size=1,
                points_per_unit=points,
                minimum_points=points,
                public_description=description,
            )
            for module, display_name, billing_unit, points, description in LEGACY_MODULE_PRICES
        ]
    )
    await db.commit()


def plan_to_out(plan: PlanSkuVersion) -> PlanOut:
    return PlanOut(
        id=plan.id,
        code=plan.code,
        version=plan.version,
        status=plan.status,
        name=plan.name,
        subtitle=plan.subtitle,
        description=plan.description,
        badge=plan.badge,
        sortOrder=plan.sort_order,
        skuType=plan.sku_type,
        audience=plan.audience,
        durationDays=plan.duration_days,
        monthlyPoints=plan.monthly_points,
        oneTimePoints=plan.one_time_points,
        listPriceCents=plan.list_price_cents,
        displayPriceCents=plan.display_price_cents,
        entitlements=json.loads(plan.entitlements_json or "[]"),
        maxConcurrency=plan.max_concurrency,
        maxResolution=plan.max_resolution,
        purchaseInstructions=plan.purchase_instructions,
        effectiveAt=plan.effective_at,
        publishedAt=plan.published_at,
        retiredAt=plan.retired_at,
    )


def module_admin_to_out(price: ModulePrice) -> ModulePriceAdminOut:
    return ModulePriceAdminOut(
        module=price.module,
        displayName=price.display_name,
        billingUnit=cast(BillingUnit, price.billing_unit),
        unitSize=price.unit_size,
        pointsPerUnit=price.points_per_unit,
        minimumPoints=price.minimum_points,
        enabled=price.enabled,
        publicDescription=price.public_description,
        internalCostCentsPerUnit=price.internal_cost_cents_per_unit,
        targetMarginBps=price.target_margin_bps,
    )


def module_public_to_out(price: ModulePrice) -> ModulePricePublicOut:
    return ModulePricePublicOut(
        module=price.module,
        displayName=price.display_name,
        billingUnit=price.billing_unit,
        unitSize=price.unit_size,
        pointsPerUnit=price.points_per_unit,
        minimumPoints=price.minimum_points,
        publicDescription=price.public_description,
    )


async def create_plan(db: AsyncSession, body: PlanCreateIn, created_by: str) -> PlanOut:
    sku = await repo.get_sku_by_code(db, body.code)
    if sku is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "SKU_EXISTS", "message": "SKU 编码已存在，请克隆新版本"},
        )
    sku = PlanSku(code=body.code)
    db.add(sku)
    await db.flush()
    plan = PlanSkuVersion(
        sku_id=sku.id,
        code=body.code,
        version=1,
        status="draft",
        name=body.name,
        subtitle=body.subtitle,
        description=body.description,
        badge=body.badge,
        sort_order=body.sortOrder,
        sku_type=body.skuType,
        audience=body.audience,
        duration_days=body.durationDays,
        monthly_points=body.monthlyPoints,
        one_time_points=body.oneTimePoints,
        list_price_cents=body.listPriceCents,
        display_price_cents=body.displayPriceCents,
        entitlements_json=json.dumps(body.entitlements, ensure_ascii=False),
        max_concurrency=body.maxConcurrency,
        max_resolution=body.maxResolution,
        purchase_instructions=body.purchaseInstructions,
        created_by=created_by,
    )
    await repo.create_plan_version(db, plan)
    await db.commit()
    await db.refresh(plan)
    await write_audit("plan_created", user_id=created_by, detail=f"plan={plan.id},code={plan.code},version=1")
    return plan_to_out(plan)


async def clone_plan(db: AsyncSession, plan_id: str, created_by: str) -> PlanOut:
    source = await repo.get_plan_version(db, plan_id)
    if not source:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "PLAN_NOT_FOUND", "message": "套餐不存在"})
    latest = await repo.latest_plan_version(db, source.sku_id)
    plan = PlanSkuVersion(
        sku_id=source.sku_id,
        code=source.code,
        version=(latest.version if latest else source.version) + 1,
        status="draft",
        name=source.name,
        subtitle=source.subtitle,
        description=source.description,
        badge=source.badge,
        sort_order=source.sort_order,
        sku_type=source.sku_type,
        audience=source.audience,
        duration_days=source.duration_days,
        monthly_points=source.monthly_points,
        one_time_points=source.one_time_points,
        list_price_cents=source.list_price_cents,
        display_price_cents=source.display_price_cents,
        entitlements_json=source.entitlements_json,
        max_concurrency=source.max_concurrency,
        max_resolution=source.max_resolution,
        purchase_instructions=source.purchase_instructions,
        created_by=created_by,
    )
    await repo.create_plan_version(db, plan)
    await db.commit()
    await db.refresh(plan)
    await write_audit(
        "plan_cloned",
        user_id=created_by,
        detail=f"source={source.id},plan={plan.id},code={plan.code},version={plan.version}",
    )
    return plan_to_out(plan)


async def publish_plan(
    db: AsyncSession,
    plan_id: str,
    admin_id: str = "",
    effective_at: datetime | None = None,
) -> PlanOut:
    plan = await repo.get_plan_version(db, plan_id)
    if not plan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "PLAN_NOT_FOUND", "message": "套餐不存在"})
    if plan.status != "draft":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "PLAN_VERSION_LOCKED", "message": "套餐版本已锁定，请克隆新版本后发布"},
        )
    published = await repo.publish_plan(db, plan, effective_at)
    await write_audit(
        "plan_published",
        user_id=admin_id,
        detail=f"plan={plan.id},code={plan.code},version={plan.version}",
    )
    return plan_to_out(published)


async def retire_plan(db: AsyncSession, plan_id: str, admin_id: str = "") -> PlanOut:
    plan = await repo.get_plan_version(db, plan_id)
    if not plan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "PLAN_NOT_FOUND", "message": "套餐不存在"})
    retired = await repo.retire_plan(db, plan)
    await write_audit(
        "plan_retired",
        user_id=admin_id,
        detail=f"plan={plan.id},code={plan.code},version={plan.version}",
    )
    return plan_to_out(retired)


async def list_public_plans(db: AsyncSession) -> list[PlanOut]:
    return [plan_to_out(p) for p in await repo.public_plans(db)]


async def upsert_module_price(db: AsyncSession, version_id: str, module: str, values: dict) -> ModulePriceAdminOut:
    if module not in ALLOWED_MODULES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail={"code": "UNKNOWN_MODULE", "message": "模块不存在"})
    billing_unit = str(values.get("billing_unit") or "")
    if billing_unit not in MODULE_BILLING_UNITS[module]:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "UNSUPPORTED_BILLING_UNIT",
                "message": f"{module} 不支持 {billing_unit} 计费",
            },
        )
    version = await repo.get_price_version(db, version_id)
    if not version:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "PRICE_VERSION_NOT_FOUND", "message": "价格版本不存在"},
        )
    if version.status != "draft":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "PRICE_VERSION_LOCKED", "message": "价格版本已锁定"},
        )
    price = await repo.upsert_module_price(db, version_id, module, values)
    return module_admin_to_out(price)


async def get_public_price_catalog(db: AsyncSession) -> tuple[str, datetime | None, list[ModulePricePublicOut]]:
    version = await repo.active_price_version(db)
    if not version:
        return "", None, []
    return (
        version.version,
        version.effective_at or version.published_at,
        [module_public_to_out(p) for p in await repo.module_prices(db, version.id)],
    )


def quote_points(price: ModulePrice, quantity: int) -> int:
    units = math.ceil(max(quantity, 0) / price.unit_size)
    return max(price.minimum_points, units * price.points_per_unit)


async def build_quote(db: AsyncSession, items: list[dict]) -> dict:
    version = await repo.active_price_version(db)
    if not version:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "NO_PRICE_VERSION", "message": "未发布价格版本"},
        )
    prices = {p.module: p for p in await repo.module_prices(db, version.id)}
    from app.core.config import get_settings
    from app.core.dynamic_config import get_config

    provider_switches = {
        "topic_generation": "deepseek_enabled",
        "script_generation": "deepseek_enabled",
        "asr": "dashscope_enabled",
        "tts": "feiying_enabled",
        "voice_clone": "feiying_enabled",
        "digital_human": "feiying_enabled",
    }
    quote_items = []
    total = 0
    for item in items:
        module = str(item["module"])
        price = prices.get(module)
        if not price:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail={"code": "PRICE_NOT_FOUND", "message": f"{module} 未配置价格"},
            )
        if price.billing_unit not in MODULE_BILLING_UNITS[module]:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "INVALID_PRICE_CONFIGURATION",
                    "message": f"{price.display_name} 计费单位配置无效，模块已暂停",
                },
            )
        provider_switch = provider_switches.get(module)
        if get_settings().app_env not in {"dev", "test"} and provider_switch:
            enabled = (await get_config(provider_switch, "false")).lower() == "true"
            if not enabled:
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"code": "MODULE_UNAVAILABLE", "message": f"{price.display_name} 当前暂停使用"},
                )
        quantity = int(item["quantity"])
        points = quote_points(price, quantity)
        total += points
        quote_items.append(
            {
                "module": module,
                "name": price.display_name,
                "quantity": quantity,
                "unit": price.billing_unit,
                "points": points,
            }
        )
    return {
        "quoteId": f"quote_{uuid.uuid4().hex}",
        "priceVersion": version.version,
        "expiresAt": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
        "items": quote_items,
        "estimatedPoints": total,
        "_catalogVersionId": version.id,
    }
