"""套餐和模块积分价格目录路由。"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.db import get_db
from app.core.deps import require_admin

from . import repository as repo
from .schemas import (
    ModulePriceCatalogOut,
    ModulePriceIn,
    PlanCreateIn,
    PlanOut,
    PriceVersionCreateIn,
    PriceVersionOut,
    PublishIn,
)
from .service import (
    clone_plan,
    create_plan,
    get_public_price_catalog,
    list_public_plans,
    module_admin_to_out,
    publish_plan,
    retire_plan,
    upsert_module_price,
)

router = APIRouter(prefix="/catalog", tags=["catalog"])
admin_router = APIRouter(tags=["admin-catalog"])


@router.get("/plans", response_model=list[PlanOut])
async def api_public_plans(db: AsyncSession = Depends(get_db)):
    return await list_public_plans(db)


@router.get("/module-prices", response_model=ModulePriceCatalogOut)
async def api_public_module_prices(db: AsyncSession = Depends(get_db)):
    version, updated_at, items = await get_public_price_catalog(db)
    return ModulePriceCatalogOut(version=version, updatedAt=updated_at, items=items)


@admin_router.post("/plans", status_code=201, response_model=PlanOut)
async def api_admin_create_plan(
    body: PlanCreateIn,
    admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await create_plan(db, body, admin_id)


@admin_router.get("/plans", response_model=list[PlanOut])
async def api_admin_list_plans(
    _admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select

    from .models import PlanSkuVersion
    from .service import plan_to_out

    await repo.promote_due_plan_versions(db)
    rows = await db.execute(select(PlanSkuVersion).order_by(PlanSkuVersion.created_at.desc()))
    return [plan_to_out(p) for p in rows.scalars().all()]


@admin_router.post("/plans/{plan_id}/publish", response_model=PlanOut)
async def api_admin_publish_plan(
    plan_id: str,
    body: PublishIn | None = None,
    admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await publish_plan(db, plan_id, admin_id, body.effectiveAt if body else None)


@admin_router.post("/plans/{plan_id}/clone", response_model=PlanOut)
async def api_admin_clone_plan(
    plan_id: str,
    admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await clone_plan(db, plan_id, admin_id)


@admin_router.post("/plans/{plan_id}/retire", response_model=PlanOut)
async def api_admin_retire_plan(
    plan_id: str,
    admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    return await retire_plan(db, plan_id, admin_id)


@admin_router.post("/price-versions", status_code=201, response_model=PriceVersionOut)
async def api_admin_create_price_version(
    body: PriceVersionCreateIn,
    admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if await repo.get_price_version_by_name(db, body.version):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "PRICE_VERSION_EXISTS", "message": "价格版本已存在"},
        )
    item = await repo.create_price_version(db, body.version, admin_id)
    await write_audit(
        "price_version_created",
        user_id=admin_id,
        detail=f"price_version={item.id},version={item.version}",
    )
    return PriceVersionOut(id=item.id, version=item.version, status=item.status)


@admin_router.get("/price-versions", response_model=list[PriceVersionOut])
async def api_admin_list_price_versions(
    _admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await repo.promote_due_price_version(db)
    versions = await repo.list_price_versions(db)
    return [
        PriceVersionOut(
            id=item.id,
            version=item.version,
            status=item.status,
            effectiveAt=item.effective_at,
            publishedAt=item.published_at,
            retiredAt=item.retired_at,
        )
        for item in versions
    ]


@admin_router.get("/price-versions/{version_id}/modules")
async def api_admin_list_module_prices(
    version_id: str,
    _admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    version = await repo.get_price_version(db, version_id)
    if version is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "PRICE_VERSION_NOT_FOUND", "message": "价格版本不存在"},
        )
    return [module_admin_to_out(item) for item in await repo.all_module_prices(db, version_id)]


@admin_router.put("/price-versions/{version_id}/modules/{module}")
async def api_admin_put_module_price(
    version_id: str,
    module: str,
    body: ModulePriceIn,
    admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    price = await upsert_module_price(
        db,
        version_id,
        module,
        {
            "display_name": body.displayName,
            "billing_unit": body.billingUnit,
            "unit_size": body.unitSize,
            "points_per_unit": body.pointsPerUnit,
            "minimum_points": body.minimumPoints,
            "enabled": body.enabled,
            "public_description": body.publicDescription,
            "internal_cost_cents_per_unit": body.internalCostCentsPerUnit,
            "target_margin_bps": body.targetMarginBps,
        },
    )
    await write_audit(
        "module_price_updated",
        user_id=admin_id,
        detail=f"price_version={version_id},module={module},points={body.pointsPerUnit}",
    )
    return price


@admin_router.post("/price-versions/{version_id}/publish", response_model=PriceVersionOut)
async def api_admin_publish_price_version(
    version_id: str,
    body: PublishIn | None = None,
    admin_id: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    item = await repo.get_price_version(db, version_id)
    if item is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "PRICE_VERSION_NOT_FOUND", "message": "价格版本不存在"},
        )
    if item.status != "draft":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "PRICE_VERSION_LOCKED", "message": "价格版本已锁定"},
        )
    if not await repo.module_prices(db, version_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "EMPTY_PRICE_VERSION", "message": "至少配置一个启用模块后才能发布"},
        )
    item = await repo.publish_price_version(db, item, body.effectiveAt if body else None)
    await write_audit(
        "price_version_published",
        user_id=admin_id,
        detail=f"price_version={item.id},version={item.version}",
    )
    return PriceVersionOut(
        id=item.id,
        version=item.version,
        status=item.status,
        effectiveAt=item.effective_at,
        publishedAt=item.published_at,
        retiredAt=item.retired_at,
    )
