"""套餐与价格目录数据访问。"""
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ModulePrice, PlanSku, PlanSkuVersion, PriceCatalogVersion


async def get_sku_by_code(db: AsyncSession, code: str) -> PlanSku | None:
    return (await db.execute(select(PlanSku).where(PlanSku.code == code))).scalar_one_or_none()


async def get_plan_version(db: AsyncSession, version_id: str) -> PlanSkuVersion | None:
    return (await db.execute(select(PlanSkuVersion).where(PlanSkuVersion.id == version_id))).scalar_one_or_none()


async def latest_plan_version(db: AsyncSession, sku_id: str) -> PlanSkuVersion | None:
    return (
        await db.execute(
            select(PlanSkuVersion)
            .where(PlanSkuVersion.sku_id == sku_id)
            .order_by(PlanSkuVersion.version.desc())
        )
    ).scalar_one_or_none()


async def create_plan_version(db: AsyncSession, plan: PlanSkuVersion) -> PlanSkuVersion:
    db.add(plan)
    await db.flush()
    await db.refresh(plan)
    return plan


async def promote_due_plan_versions(db: AsyncSession) -> None:
    """将到期的定时套餐原子提升为 published，并下架同 SKU 的旧版本。"""
    now = datetime.now(UTC)
    rows = await db.execute(
        select(PlanSkuVersion)
        .where(PlanSkuVersion.status == "scheduled", PlanSkuVersion.effective_at <= now)
        .order_by(PlanSkuVersion.effective_at.desc(), PlanSkuVersion.version.desc())
    )
    selected: dict[str, PlanSkuVersion] = {}
    due = list(rows.scalars().all())
    for item in due:
        selected.setdefault(item.sku_id, item)
    if not selected:
        return
    for sku_id, current in selected.items():
        await db.execute(
            update(PlanSkuVersion)
            .where(
                PlanSkuVersion.sku_id == sku_id,
                PlanSkuVersion.id != current.id,
                or_(
                    PlanSkuVersion.status == "published",
                    and_(PlanSkuVersion.status == "scheduled", PlanSkuVersion.effective_at <= now),
                ),
            )
            .values(status="retired", retired_at=now)
        )
        current.status = "published"
        current.published_at = now
    await db.commit()


async def public_plans(db: AsyncSession) -> list[PlanSkuVersion]:
    await promote_due_plan_versions(db)
    now = datetime.now(UTC)
    rows = await db.execute(
        select(PlanSkuVersion)
        .where(
            PlanSkuVersion.audience == "public",
            or_(
                PlanSkuVersion.status == "published",
                and_(PlanSkuVersion.status == "scheduled", PlanSkuVersion.effective_at <= now),
            ),
        )
        .order_by(PlanSkuVersion.code.asc(), PlanSkuVersion.version.desc())
    )
    latest_by_sku: dict[str, PlanSkuVersion] = {}
    for plan in rows.scalars().all():
        latest_by_sku.setdefault(plan.sku_id, plan)
    return sorted(latest_by_sku.values(), key=lambda item: (item.sort_order, item.display_price_cents, item.created_at))


async def publish_plan(
    db: AsyncSession,
    plan: PlanSkuVersion,
    effective_at: datetime | None = None,
) -> PlanSkuVersion:
    now = datetime.now(UTC)
    normalized_effective = effective_at
    if normalized_effective and normalized_effective.tzinfo is None:
        normalized_effective = normalized_effective.replace(tzinfo=UTC)
    if normalized_effective and normalized_effective > now:
        plan.status = "scheduled"
        plan.effective_at = normalized_effective
        await db.commit()
        await db.refresh(plan)
        return plan
    await db.execute(
        update(PlanSkuVersion)
        .where(
            PlanSkuVersion.sku_id == plan.sku_id,
            PlanSkuVersion.status == "published",
            PlanSkuVersion.id != plan.id,
        )
        .values(status="retired", retired_at=now)
    )
    plan.status = "published"
    plan.effective_at = normalized_effective or now
    plan.published_at = now
    await db.commit()
    await db.refresh(plan)
    return plan


async def retire_plan(db: AsyncSession, plan: PlanSkuVersion) -> PlanSkuVersion:
    plan.status = "retired"
    plan.retired_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(plan)
    return plan


async def get_price_version(db: AsyncSession, version_id: str) -> PriceCatalogVersion | None:
    return (
        await db.execute(select(PriceCatalogVersion).where(PriceCatalogVersion.id == version_id))
    ).scalar_one_or_none()


async def get_price_version_by_name(db: AsyncSession, version: str) -> PriceCatalogVersion | None:
    return (
        await db.execute(select(PriceCatalogVersion).where(PriceCatalogVersion.version == version))
    ).scalar_one_or_none()


async def create_price_version(db: AsyncSession, version: str, created_by: str) -> PriceCatalogVersion:
    item = PriceCatalogVersion(version=version, created_by=created_by)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def upsert_module_price(
    db: AsyncSession,
    catalog_version_id: str,
    module: str,
    values: dict,
) -> ModulePrice:
    existing = (
        await db.execute(
            select(ModulePrice).where(
                ModulePrice.catalog_version_id == catalog_version_id,
                ModulePrice.module == module,
            )
        )
    ).scalar_one_or_none()
    if existing:
        for key, value in values.items():
            setattr(existing, key, value)
        await db.commit()
        await db.refresh(existing)
        return existing
    item = ModulePrice(catalog_version_id=catalog_version_id, module=module, **values)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def publish_price_version(
    db: AsyncSession,
    item: PriceCatalogVersion,
    effective_at: datetime | None = None,
) -> PriceCatalogVersion:
    now = datetime.now(UTC)
    normalized_effective = effective_at
    if normalized_effective and normalized_effective.tzinfo is None:
        normalized_effective = normalized_effective.replace(tzinfo=UTC)
    if normalized_effective and normalized_effective > now:
        item.status = "scheduled"
        item.effective_at = normalized_effective
        await db.commit()
        await db.refresh(item)
        return item
    await db.execute(
        update(PriceCatalogVersion)
        .where(PriceCatalogVersion.status == "published")
        .values(status="retired", retired_at=now)
    )
    item.status = "published"
    item.effective_at = normalized_effective or now
    item.published_at = now
    await db.commit()
    await db.refresh(item)
    return item


async def promote_due_price_version(db: AsyncSession) -> None:
    """价格目录全局只保留最新一个已生效版本。"""
    now = datetime.now(UTC)
    current = (
        await db.execute(
            select(PriceCatalogVersion)
            .where(
                PriceCatalogVersion.status == "scheduled",
                PriceCatalogVersion.effective_at <= now,
            )
            .order_by(PriceCatalogVersion.effective_at.desc(), PriceCatalogVersion.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if current is None:
        return
    await db.execute(
        update(PriceCatalogVersion)
        .where(
            PriceCatalogVersion.id != current.id,
            or_(
                PriceCatalogVersion.status == "published",
                and_(PriceCatalogVersion.status == "scheduled", PriceCatalogVersion.effective_at <= now),
            ),
        )
        .values(status="retired", retired_at=now)
    )
    current.status = "published"
    current.published_at = now
    await db.commit()


async def active_price_version(db: AsyncSession) -> PriceCatalogVersion | None:
    await promote_due_price_version(db)
    now = datetime.now(UTC)
    return (
        await db.execute(
            select(PriceCatalogVersion)
            .where(
                or_(
                    PriceCatalogVersion.status == "published",
                    and_(
                        PriceCatalogVersion.status == "scheduled",
                        PriceCatalogVersion.effective_at <= now,
                    ),
                )
            )
            .order_by(PriceCatalogVersion.effective_at.desc(), PriceCatalogVersion.published_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def list_price_versions(db: AsyncSession) -> list[PriceCatalogVersion]:
    rows = await db.execute(select(PriceCatalogVersion).order_by(PriceCatalogVersion.created_at.desc()))
    return list(rows.scalars().all())


async def module_prices(db: AsyncSession, catalog_version_id: str) -> list[ModulePrice]:
    rows = await db.execute(
        select(ModulePrice)
        .where(ModulePrice.catalog_version_id == catalog_version_id, ModulePrice.enabled.is_(True))
        .order_by(ModulePrice.module.asc())
    )
    return list(rows.scalars().all())


async def all_module_prices(db: AsyncSession, catalog_version_id: str) -> list[ModulePrice]:
    rows = await db.execute(
        select(ModulePrice)
        .where(ModulePrice.catalog_version_id == catalog_version_id)
        .order_by(ModulePrice.module.asc())
    )
    return list(rows.scalars().all())
