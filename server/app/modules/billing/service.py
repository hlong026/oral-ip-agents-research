"""报价、积分批次、冻结、结算与退款业务编排。"""

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.core.logging import get_logger

from . import repository as repo
from .models import CreditGrant, CreditLedger, CreditReservation, PriceQuote, QuotaAccount, QuotaUsage
from .schemas import QuotaOut, ReservationBatchOut, ReservationItemOut, ReservationStateOut, UsageItemOut

INITIAL_GRANT = 12430.0  # 开户礼点数（对齐效果图额度卡）
logger = get_logger("oral.billing")


async def grant_initial_quota(db: AsyncSession, user_id: str) -> None:
    await grant_points(
        db,
        user_id,
        int(INITIAL_GRANT),
        source_type="trial",
        source_id="initial-grant",
        expires_at=datetime.now(UTC) + timedelta(days=30),
        commit=True,
    )


async def grant_points(
    db: AsyncSession,
    user_id: str,
    points: int,
    *,
    source_type: str,
    source_id: str,
    expires_at: datetime | None,
    created_by: str = "system",
    event_type: str = "grant",
    commit: bool = False,
) -> QuotaAccount:
    """追加积分来源与不可变流水；调用方可选择并入现有业务事务。"""
    if points <= 0:
        return await repo.ensure_account(db, user_id)
    account = await repo.ensure_account(db, user_id)
    account.balance += points
    account.total_granted += points
    db.add(
        CreditGrant(
            user_id=user_id,
            source_type=source_type,
            source_id=source_id,
            granted_points=points,
            remaining_points=points,
            expires_at=expires_at,
        )
    )
    db.add(
        CreditLedger(
            user_id=user_id,
            event_type=event_type,
            points_delta=points,
            reference_type="grant",
            reference_id=source_id,
            created_by=created_by,
        )
    )
    if commit:
        await db.commit()
        await db.refresh(account)
    else:
        await db.flush()
    return account


async def adjust_points(
    db: AsyncSession,
    user_id: str,
    points: int,
    reason: str,
    admin_id: str,
    expires_at: datetime | None = None,
) -> QuotaOut:
    """管理员积分调整只能追加 grant/ledger，不提供直接改余额接口。"""
    if points == 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "ZERO_ADJUSTMENT", "message": "调整积分不能为 0"},
        )
    reference_id = f"manual:{uuid.uuid4().hex}"
    if points > 0:
        await grant_points(
            db,
            user_id,
            points,
            source_type="manual",
            source_id=reference_id,
            expires_at=expires_at or datetime.now(UTC) + timedelta(days=365),
            created_by=admin_id,
            event_type="adjustment",
        )
        ledger = (
            await db.execute(
                select(CreditLedger).where(
                    CreditLedger.reference_id == reference_id,
                    CreditLedger.event_type == "adjustment",
                )
            )
        ).scalar_one()
        ledger.detail_json = json.dumps({"reason": reason}, ensure_ascii=False)
        await db.commit()
        return await get_quota(db, user_id)

    amount = abs(points)
    now = datetime.now(UTC)
    grants = list(
        (
            await db.execute(
                select(CreditGrant)
                .where(
                    CreditGrant.user_id == user_id,
                    CreditGrant.remaining_points > 0,
                    or_(CreditGrant.expires_at.is_(None), CreditGrant.expires_at > now),
                )
                .order_by(
                    CreditGrant.expires_at.is_(None),
                    CreditGrant.expires_at.asc(),
                    CreditGrant.created_at.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    if sum(item.remaining_points for item in grants) < amount:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "INSUFFICIENT_POINTS", "message": "用户有效积分不足，无法扣减"},
        )
    allocations: list[dict[str, int | str]] = []
    needed = amount
    for grant in grants:
        used = min(grant.remaining_points, needed)
        if used <= 0:
            continue
        result = await db.execute(
            update(CreditGrant)
            .where(CreditGrant.id == grant.id, CreditGrant.remaining_points == grant.remaining_points)
            .values(remaining_points=CreditGrant.remaining_points - used)
            .execution_options(synchronize_session=False)
        )
        if int(getattr(result, "rowcount", 0) or 0) != 1:
            await db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "CREDIT_CONFLICT", "message": "积分余额正在变化，请重试"},
            )
        allocations.append({"grantId": grant.id, "points": used})
        needed -= used
        if needed == 0:
            break
    account_result = await db.execute(
        update(QuotaAccount)
        .where(QuotaAccount.user_id == user_id, QuotaAccount.balance >= amount)
        .values(balance=QuotaAccount.balance - amount)
    )
    if int(getattr(account_result, "rowcount", 0) or 0) != 1:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "CREDIT_CONFLICT", "message": "积分余额正在变化，请重试"},
        )
    db.add(
        CreditLedger(
            user_id=user_id,
            event_type="adjustment",
            points_delta=points,
            reference_type="manual",
            reference_id=reference_id,
            created_by=admin_id,
            detail_json=json.dumps({"reason": reason, "allocations": allocations}, ensure_ascii=False),
        )
    )
    await db.commit()
    return await get_quota(db, user_id)


async def get_quota(db: AsyncSession, user_id: str) -> QuotaOut:
    from app.modules.activation.service import grant_due_subscription_points

    await grant_due_subscription_points(db, user_id)
    acc = await repo.ensure_account(db, user_id)
    active_balance = int(
        (
            await db.scalar(
                select(func.coalesce(func.sum(CreditGrant.remaining_points), 0)).where(
                    CreditGrant.user_id == user_id,
                    CreditGrant.remaining_points > 0,
                    or_(CreditGrant.expires_at.is_(None), CreditGrant.expires_at > datetime.now(UTC)),
                )
            )
        )
        or 0
    )
    if acc.balance != active_balance:
        acc.balance = active_balance
        await db.commit()
    return QuotaOut(balance=acc.balance, usedThisMonth=acc.used_this_month, total=acc.total_granted)


async def save_quote(db: AsyncSession, user_id: str, quote: dict, catalog_version_id: str) -> None:
    db.add(
        PriceQuote(
            id=str(quote["quoteId"]),
            user_id=user_id,
            catalog_version_id=catalog_version_id,
            price_version=str(quote["priceVersion"]),
            items_json=json.dumps(quote["items"], ensure_ascii=False),
            estimated_points=int(quote["estimatedPoints"]),
            expires_at=datetime.fromisoformat(str(quote["expiresAt"])),
        )
    )
    await db.commit()


async def reserve_quote(
    db: AsyncSession,
    user_id: str,
    quote_id: str,
    count: int = 1,
    task: dict | None = None,
    operation: dict | None = None,
    commit: bool = True,
) -> ReservationBatchOut:
    """原子冻结报价积分；同一 quote 只能成功冻结一次。"""
    count = max(1, min(count, 20))
    quote = (
        await db.execute(select(PriceQuote).where(PriceQuote.id == quote_id, PriceQuote.user_id == user_id))
    ).scalar_one_or_none()
    if quote is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "QUOTE_NOT_FOUND", "message": "报价不存在"})
    if quote.status != "quoted":
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "QUOTE_ALREADY_USED", "message": "报价已使用"})
    if task is not None:
        _validate_quote_matches_task(quote, task)
    if operation is not None:
        _validate_quote_matches_operation(quote, operation)
    expires_at = quote.expires_at if quote.expires_at.tzinfo else quote.expires_at.replace(tzinfo=UTC)
    if expires_at < datetime.now(UTC):
        quote.status = "expired"
        await db.commit()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "QUOTE_EXPIRED", "message": "报价已过期，请重新报价"},
        )
    now = datetime.now(UTC)
    claimed = await db.execute(
        update(PriceQuote)
        .where(
            PriceQuote.id == quote_id,
            PriceQuote.user_id == user_id,
            PriceQuote.status == "quoted",
            PriceQuote.expires_at >= now,
        )
        .values(status="reserved")
        .execution_options(synchronize_session=False)
    )
    if int(getattr(claimed, "rowcount", 0) or 0) != 1:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "QUOTE_ALREADY_USED", "message": "报价已使用"},
        )

    if await _is_billing_exempt_admin(db, user_id):
        reservations = [
            CreditReservation(
                user_id=user_id,
                quote_id=quote.id,
                reserved_points=0,
            )
            for _ in range(count)
        ]
        db.add_all(reservations)
        await db.flush()
        if commit:
            await db.commit()
        account = await repo.get_account(db, user_id)
        logger.info("admin_quota_exempt_reservation", user_id=user_id, quote_id=quote.id, count=count)
        return ReservationBatchOut(
            items=[
                ReservationItemOut(
                    id=item.id,
                    quoteId=item.quote_id,
                    reservedPoints=0,
                    status=item.status,
                )
                for item in reservations
            ],
            availablePoints=account.balance if account else 0,
        )

    await repo.ensure_account(db, user_id)
    total = quote.estimated_points * count
    grants = list(
        (
            await db.execute(
                select(CreditGrant)
                .where(
                    CreditGrant.user_id == user_id,
                    CreditGrant.remaining_points > 0,
                    or_(CreditGrant.expires_at.is_(None), CreditGrant.expires_at > now),
                )
                .order_by(
                    CreditGrant.expires_at.is_(None),
                    CreditGrant.expires_at.asc(),
                    CreditGrant.created_at.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    if sum(item.remaining_points for item in grants) < total:
        await db.rollback()
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "QUOTA_EXHAUSTED", "message": "有效积分不足，无法开始任务"},
        )

    remaining_by_grant = {item.id: item.remaining_points for item in grants}
    reservation_allocations: list[list[dict[str, int | str]]] = []
    used_by_grant: dict[str, int] = {}
    for _ in range(count):
        needed = quote.estimated_points
        allocations: list[dict[str, int | str]] = []
        for grant in grants:
            available = remaining_by_grant[grant.id]
            if available <= 0:
                continue
            used = min(available, needed)
            remaining_by_grant[grant.id] -= used
            used_by_grant[grant.id] = used_by_grant.get(grant.id, 0) + used
            allocations.append({"grantId": grant.id, "points": used})
            needed -= used
            if needed == 0:
                break
        reservation_allocations.append(allocations)

    for grant in grants:
        used = used_by_grant.get(grant.id, 0)
        if used == 0:
            continue
        result = await db.execute(
            update(CreditGrant)
            .where(
                CreditGrant.id == grant.id,
                CreditGrant.remaining_points == grant.remaining_points,
            )
            .values(remaining_points=CreditGrant.remaining_points - used)
            .execution_options(synchronize_session=False)
        )
        if int(getattr(result, "rowcount", 0) or 0) != 1:
            await db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "CREDIT_CONFLICT", "message": "积分余额正在变化，请重试"},
            )

    result = await db.execute(
        update(QuotaAccount)
        .where(QuotaAccount.user_id == user_id, QuotaAccount.balance >= total)
        .values(balance=QuotaAccount.balance - total)
    )
    if int(getattr(result, "rowcount", 0) or 0) != 1:
        await db.rollback()
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            detail={"code": "QUOTA_EXHAUSTED", "message": "积分不足，无法开始任务"},
        )

    reservations = [
        CreditReservation(
            user_id=user_id,
            quote_id=quote.id,
            reserved_points=quote.estimated_points,
            allocations_json=json.dumps(allocations, ensure_ascii=False),
        )
        for allocations in reservation_allocations
    ]
    db.add_all(reservations)
    await db.flush()
    for reservation in reservations:
        db.add(
            CreditLedger(
                user_id=user_id,
                event_type="reserve",
                points_delta=-reservation.reserved_points,
                reference_type="reservation",
                reference_id=reservation.id,
                price_version=quote.price_version,
                detail_json=json.dumps(
                    {
                        "items": json.loads(quote.items_json),
                        "allocations": json.loads(reservation.allocations_json),
                    },
                    ensure_ascii=False,
                ),
            )
        )
    if commit:
        await db.commit()
    else:
        await db.flush()
    account = await repo.get_account(db, user_id)
    return ReservationBatchOut(
        items=[
            ReservationItemOut(
                id=item.id,
                quoteId=item.quote_id,
                reservedPoints=item.reserved_points,
                status=item.status,
            )
            for item in reservations
        ],
        availablePoints=account.balance if account else 0,
    )


async def _is_billing_exempt_admin(db: AsyncSession, user_id: str) -> bool:
    """Only the explicit admin role may run validated operations without credits."""
    from app.modules.auth import repository as auth_repo

    user = await auth_repo.get_by_id(db, user_id)
    return bool(user and user.role == "admin")


def pipeline_quote_quantities(task: dict, module_units: dict[str, str]) -> dict[str, int]:
    """从服务端收到的任务参数重建单个任务用量，防止客户端删减报价模块。"""
    script_text = str(task.get("scriptText") or "").strip()
    target_duration = max(1, int(task.get("_targetDurationSeconds") or 60))
    duration_seconds = max(target_duration, int(len(script_text) * 0.28 + 0.999999))
    text_length = max(len(script_text), int(duration_seconds / 0.28 + 0.999999))
    required_modules = {
        "script_generation",
        "tts",
        "digital_human",
        "hd_export",
    }
    if task.get("sourceUrl") and not script_text:
        required_modules.add("asr")
    if task.get("topic") and not script_text:
        required_modules.add("topic_generation")

    if not required_modules.issubset(module_units):
        return {}
    expected: dict[str, int] = {}
    for module in required_modules:
        unit = module_units[module]
        if unit in {"per_minute", "per_second"}:
            quantity = duration_seconds
        elif unit == "per_1k_chars":
            quantity = text_length
        elif unit == "per_1k_tokens":
            quantity = max(1, (text_length + 1) // 2)
        else:
            quantity = 1
        expected[module] = quantity
    return expected


def _expected_pipeline_quote(task: dict, quote_items: list[dict]) -> dict[str, int]:
    module_units = {str(item.get("module") or ""): str(item.get("unit") or "") for item in quote_items}
    return pipeline_quote_quantities(task, module_units)


def _validate_quote_matches_task(quote: PriceQuote, task: dict) -> None:
    quote_items = json.loads(quote.items_json or "[]")
    expected = _expected_pipeline_quote(task, quote_items)
    actual = {str(item.get("module") or ""): int(item.get("quantity") or 0) for item in quote_items}
    if not expected or len(actual) != len(quote_items) or actual != expected:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "QUOTE_TASK_MISMATCH", "message": "报价与当前任务参数不一致，请重新报价"},
        )


def _validate_quote_matches_operation(quote: PriceQuote, operation: dict) -> None:
    """校验独立 Provider 操作的模块和原始用量，避免复用低价报价。"""
    quote_items = json.loads(quote.items_json or "[]")
    if len(quote_items) != 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "QUOTE_OPERATION_MISMATCH", "message": "报价与当前操作不一致，请重新报价"},
        )
    item = quote_items[0]
    unit = str(item.get("unit") or "")
    measures = operation.get("measures") or {}
    quantity_by_unit = {
        "per_action": 1,
        "per_minute": max(1, int(measures.get("seconds") or 0)),
        "per_second": max(1, int(measures.get("seconds") or 0)),
        "per_1k_chars": max(1, int(measures.get("characters") or 0)),
        "per_1k_tokens": max(1, int(measures.get("tokens") or 0)),
        "per_image": max(1, int(measures.get("images") or 1)),
        "per_asset": max(1, int(measures.get("assets") or 1)),
    }
    expected_quantity = quantity_by_unit.get(unit)
    if (
        str(item.get("module") or "") != str(operation.get("module") or "")
        or expected_quantity is None
        or int(item.get("quantity") or 0) != expected_quantity
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "QUOTE_OPERATION_MISMATCH", "message": "报价与当前操作不一致，请重新报价"},
        )


@asynccontextmanager
async def metered_operation(
    db: AsyncSession,
    user_id: str,
    quote_id: str | None,
    module: str,
    measures: dict[str, int],
) -> AsyncIterator[str]:
    """为独立 Provider 调用统一执行报价冻结、成功结算和异常释放。"""
    reservation_id = await reserve_metered_operation(db, user_id, quote_id, module, measures)
    operation_id = f"operation_{uuid.uuid4().hex}"
    try:
        yield operation_id
    except BaseException:
        await recover_reservation_after_failure(db, reservation_id, user_id)
        raise
    else:
        try:
            settled = await settle_reservation(db, reservation_id, operation_id, step=module)
        except BaseException:
            await recover_reservation_after_failure(db, reservation_id, user_id)
            raise
        if settled <= 0:
            await recover_reservation_after_failure(db, reservation_id, user_id)
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "BILLING_SETTLEMENT_FAILED", "message": "积分结算失败，请稍后重试"},
            )


async def reserve_metered_operation(
    db: AsyncSession,
    user_id: str,
    quote_id: str | None,
    module: str,
    measures: dict[str, int],
) -> str:
    """冻结并校验单个 Provider 操作，供同步和异步任务共用。"""
    if not quote_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "QUOTE_REQUIRED", "message": "该操作需要先确认积分报价"},
        )
    batch = await reserve_quote(
        db,
        user_id,
        quote_id,
        operation={"module": module, "measures": measures},
    )
    return batch.items[0].id


async def quote_operation_unit(
    db: AsyncSession,
    user_id: str,
    quote_id: str | None,
    module: str,
) -> str:
    """读取一次性报价的单模块计费单位，供执行前选择可验证的计量方式。"""
    if not quote_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "QUOTE_REQUIRED", "message": "该操作需要先确认积分报价"},
        )
    quote = (
        await db.execute(select(PriceQuote).where(PriceQuote.id == quote_id, PriceQuote.user_id == user_id))
    ).scalar_one_or_none()
    items = json.loads(quote.items_json or "[]") if quote else []
    if len(items) != 1 or str(items[0].get("module") or "") != module:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "QUOTE_OPERATION_MISMATCH", "message": "报价与当前操作不一致，请重新报价"},
        )
    return str(items[0].get("unit") or "")


async def attach_reservation(db: AsyncSession, reservation_id: str, user_id: str, task_id: str) -> None:
    result = await db.execute(
        update(CreditReservation)
        .where(
            CreditReservation.id == reservation_id,
            CreditReservation.user_id == user_id,
            CreditReservation.status == "reserved",
            CreditReservation.task_id == "",
        )
        .values(task_id=task_id)
    )
    if int(getattr(result, "rowcount", 0) or 0) != 1:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "RESERVATION_UNAVAILABLE", "message": "积分冻结不可用"},
        )
    await db.flush()


async def settle_reservation(
    db: AsyncSession,
    reservation_id: str,
    task_id: str = "",
    *,
    step: str = "pipeline",
) -> int:
    """幂等结算：同一 reservation 只允许一次 settled 状态转换。

    通过 CAS (WHERE status='reserved') + settled_by 唯一跟踪确保
    轮询和 Webhook 重复触发不会重复结算。
    """
    reservation = (
        await db.execute(select(CreditReservation).where(CreditReservation.id == reservation_id))
    ).scalar_one_or_none()
    if reservation is None:
        return 0
    if reservation.status == "settled":
        return reservation.actual_points or 1
    if reservation.status != "reserved":
        return 0
    quote = await db.get(PriceQuote, reservation.quote_id)
    now = datetime.now(UTC)
    settle_claimant = task_id or reservation.task_id or reservation_id
    result = await db.execute(
        update(CreditReservation)
        .where(CreditReservation.id == reservation_id, CreditReservation.status == "reserved")
        .values(
            status="settled",
            actual_points=reservation.reserved_points,
            settled_at=now,
            settled_by=settle_claimant,
            task_id=task_id or reservation.task_id,
        )
    )
    if int(getattr(result, "rowcount", 0) or 0) != 1:
        await db.rollback()
        current = await db.get(CreditReservation, reservation_id)
        return (current.actual_points or 1) if current and current.status == "settled" else 0
    if reservation.reserved_points == 0:
        await db.commit()
        return 1
    await db.execute(
        update(QuotaAccount)
        .where(QuotaAccount.user_id == reservation.user_id)
        .values(used_this_month=QuotaAccount.used_this_month + reservation.reserved_points)
    )
    db.add(
        CreditLedger(
            user_id=reservation.user_id,
            event_type="settle",
            points_delta=0,
            reference_type="reservation",
            reference_id=reservation.id,
            price_version=quote.price_version if quote else "",
            task_id=task_id or reservation.task_id,
            detail_json=json.dumps(
                {
                    "items": json.loads(quote.items_json) if quote else [],
                    "allocations": json.loads(reservation.allocations_json or "[]"),
                    "actualPoints": reservation.reserved_points,
                },
                ensure_ascii=False,
            ),
        )
    )
    db.add(
        QuotaUsage(
            user_id=reservation.user_id,
            trace_id=task_id or reservation.task_id or reservation.id,
            task_id=task_id or reservation.task_id,
            step=step,
            resolution="quoted",
            points=reservation.reserved_points,
            compute="cloud",
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        # 唯一索引兖底：视为已被其他路径结算
        await db.rollback()
        logger.warning(
            "settle_idempotent_guard_hit",
            reservation_id=reservation_id,
            task_id=task_id,
        )
        return reservation.reserved_points
    return reservation.reserved_points


async def release_reservation(
    db: AsyncSession,
    reservation_id: str,
    user_id: str | None = None,
) -> ReservationStateOut | None:
    query = select(CreditReservation).where(CreditReservation.id == reservation_id)
    if user_id:
        query = query.where(CreditReservation.user_id == user_id)
    reservation = (await db.execute(query)).scalar_one_or_none()
    if reservation is None:
        return None
    if reservation.status == "reserved":
        result = await db.execute(
            update(CreditReservation)
            .where(CreditReservation.id == reservation.id, CreditReservation.status == "reserved")
            .values(status="released", settled_at=datetime.now(UTC))
        )
        if int(getattr(result, "rowcount", 0) or 0) == 1:
            if reservation.reserved_points == 0:
                await db.commit()
                reservation.status = "released"
                account = await repo.get_account(db, reservation.user_id)
                return ReservationStateOut(
                    id=reservation.id,
                    status=reservation.status,
                    reservedPoints=0,
                    actualPoints=0,
                    availablePoints=account.balance if account else 0,
                )
            allocations = json.loads(reservation.allocations_json or "[]")
            if allocations:
                for allocation in allocations:
                    await db.execute(
                        update(CreditGrant)
                        .where(CreditGrant.id == str(allocation["grantId"]))
                        .values(
                            remaining_points=CreditGrant.remaining_points + int(allocation["points"]),
                        )
                    )
                active_balance = int(
                    (
                        await db.scalar(
                            select(func.coalesce(func.sum(CreditGrant.remaining_points), 0)).where(
                                CreditGrant.user_id == reservation.user_id,
                                CreditGrant.remaining_points > 0,
                                or_(
                                    CreditGrant.expires_at.is_(None),
                                    CreditGrant.expires_at > datetime.now(UTC),
                                ),
                            )
                        )
                    )
                    or 0
                )
                await db.execute(
                    update(QuotaAccount)
                    .where(QuotaAccount.user_id == reservation.user_id)
                    .values(balance=active_balance)
                )
            else:
                await db.execute(
                    update(QuotaAccount)
                    .where(QuotaAccount.user_id == reservation.user_id)
                    .values(balance=QuotaAccount.balance + reservation.reserved_points)
                )
            db.add(
                CreditLedger(
                    user_id=reservation.user_id,
                    event_type="release",
                    points_delta=reservation.reserved_points,
                    reference_type="reservation",
                    reference_id=reservation.id,
                    task_id=reservation.task_id,
                )
            )
            await db.commit()
            reservation.status = "released"
        else:
            await db.rollback()
            await db.refresh(reservation)
    account = await repo.get_account(db, reservation.user_id)
    return ReservationStateOut(
        id=reservation.id,
        status=reservation.status,
        reservedPoints=reservation.reserved_points,
        actualPoints=reservation.actual_points,
        availablePoints=account.balance if account else 0,
    )


async def recover_reservation_after_failure(
    db: AsyncSession,
    reservation_id: str,
    user_id: str,
) -> ReservationStateOut | None:
    """失败后恢复积分冻结。

    Provider 或结算中的 SQL 异常会让当前 Session 失效，必须先回滚；
    当前 Session 仍不可用时，用独立 Session 执行最后一次幂等释放。
    """
    try:
        await db.rollback()
    except Exception:
        logger.exception(
            "积分恢复前回滚会话失败",
            reservation_id=reservation_id,
            user_id=user_id,
        )

    try:
        recovered = await release_reservation(db, reservation_id, user_id)
        if recovered is not None and recovered.status in {"released", "settled"}:
            return recovered
        logger.error(
            "积分冻结恢复后仍未结束",
            reservation_id=reservation_id,
            user_id=user_id,
            reservation_status=recovered.status if recovered else "missing",
        )
    except Exception:
        logger.exception(
            "使用当前会话恢复积分冻结失败",
            reservation_id=reservation_id,
            user_id=user_id,
        )
        try:
            await db.rollback()
        except Exception:
            logger.exception(
                "重试恢复前回滚会话失败",
                reservation_id=reservation_id,
                user_id=user_id,
            )

    try:
        async with SessionLocal() as recovery_db:
            recovered = await release_reservation(recovery_db, reservation_id, user_id)
            if recovered is None or recovered.status not in {"released", "settled"}:
                logger.error(
                    "独立会话未能恢复积分冻结",
                    reservation_id=reservation_id,
                    user_id=user_id,
                    reservation_status=recovered.status if recovered else "missing",
                )
            return recovered
    except Exception:
        logger.exception(
            "独立会话恢复积分冻结失败",
            reservation_id=reservation_id,
            user_id=user_id,
        )
        return None


def usage_to_out(u: QuotaUsage) -> UsageItemOut:
    return UsageItemOut(
        id=u.id,
        traceId=u.trace_id,
        step=u.step,
        resolution=u.resolution,
        points=u.points,
        compute=u.compute,
        createdAt=u.created_at.astimezone(UTC).isoformat(),
    )


# ============ 积分过期自动清零 ============


async def expire_overdue_grants(db: AsyncSession, *, batch_size: int = 200) -> int:
    """扫描已过期的 CreditGrant 批次，将 remaining_points 清零并记录流水。

    幂等：只处理 status='active' 且 expires_at < now 且 remaining_points > 0 的批次。
    返回本次处理的批次数。
    """
    now = datetime.now(UTC)
    grants = list(
        (
            await db.execute(
                select(CreditGrant)
                .where(
                    CreditGrant.status == "active",
                    CreditGrant.expires_at.is_not(None),
                    CreditGrant.expires_at <= now,
                    CreditGrant.remaining_points > 0,
                )
                .order_by(CreditGrant.expires_at.asc())
                .limit(batch_size)
            )
        )
        .scalars()
        .all()
    )
    if not grants:
        return 0

    affected_users: dict[str, int] = {}  # user_id -> 本批次过期积分总和
    for grant in grants:
        expired_points = grant.remaining_points
        result = await db.execute(
            update(CreditGrant)
            .where(
                CreditGrant.id == grant.id,
                CreditGrant.status == "active",
                CreditGrant.remaining_points == expired_points,
            )
            .values(remaining_points=0, status="expired", expired_at=now)
            .execution_options(synchronize_session=False)
        )
        if int(getattr(result, "rowcount", 0) or 0) != 1:
            continue
        db.add(
            CreditLedger(
                user_id=grant.user_id,
                event_type="expire",
                points_delta=-expired_points,
                reference_type="grant",
                reference_id=grant.id,
                created_by="system",
                detail_json=json.dumps(
                    {"sourceType": grant.source_type, "expiredPoints": expired_points},
                    ensure_ascii=False,
                ),
            )
        )
        affected_users[grant.user_id] = affected_users.get(grant.user_id, 0) + expired_points

    # 相对扣减：避免覆盖并发消费事务的扣减
    for user_id, expired_total in affected_users.items():
        await db.execute(
            update(QuotaAccount)
            .where(QuotaAccount.user_id == user_id, QuotaAccount.balance >= expired_total)
            .values(balance=QuotaAccount.balance - expired_total)
        )

    await db.commit()
    logger.info("credit_grants_expired", count=len(grants), users=len(affected_users))
    return len(grants)


# ============ 消费明细查询 ============


async def list_ledger(
    db: AsyncSession,
    user_id: str,
    *,
    page: int = 1,
    page_size: int = 20,
    event_type: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> tuple[list[CreditLedger], int]:
    """用户端消费明细分页查询，支持按事件类型和日期范围过滤。"""
    conditions = [CreditLedger.user_id == user_id]
    if event_type:
        conditions.append(CreditLedger.event_type == event_type)
    if start_date:
        conditions.append(CreditLedger.created_at >= start_date)
    if end_date:
        conditions.append(CreditLedger.created_at <= end_date)

    total = int(
        (await db.scalar(select(func.count(CreditLedger.id)).where(*conditions))) or 0
    )
    rows = list(
        (
            await db.execute(
                select(CreditLedger)
                .where(*conditions)
                .order_by(CreditLedger.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return rows, total


async def all_ledger_for_export(
    db: AsyncSession,
    user_id: str,
    *,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> list[CreditLedger]:
    """导出用：获取指定日期范围内的全部流水。"""
    conditions = [CreditLedger.user_id == user_id]
    if start_date:
        conditions.append(CreditLedger.created_at >= start_date)
    if end_date:
        conditions.append(CreditLedger.created_at <= end_date)
    rows = list(
        (
            await db.execute(
                select(CreditLedger)
                .where(*conditions)
                .order_by(CreditLedger.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return rows
