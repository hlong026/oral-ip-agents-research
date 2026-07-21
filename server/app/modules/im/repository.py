"""im 模块数据访问层"""

from datetime import UTC, datetime

from sqlalchemy import and_, delete, exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.publish.models import PublishAccount

from .models import (
    IMAutomationConsent,
    IMAutoReplyRule,
    IMConversation,
    IMGlobalControl,
    IMGrayAccount,
    IMListenerState,
    IMMessage,
    IMMetricEvent,
)


class ListenerOwnershipConflict(RuntimeError):
    """The durable listener row already belongs to another user."""


# ---- 会话 ----


async def create_conversation(db: AsyncSession, **fields) -> IMConversation:
    c = IMConversation(**fields)
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


async def get_or_create_conversation(db: AsyncSession, **fields) -> IMConversation:
    """Return the durable account/user/remote conversation, including insert races."""
    account_id = str(fields["account_id"])
    user_id = str(fields["user_id"])
    remote_uid = str(fields["remote_uid"])
    existing = await get_conversation_by_dy_id(db, account_id, user_id, remote_uid)
    if existing is not None:
        return existing
    conversation = IMConversation(**fields)
    db.add(conversation)
    try:
        await db.commit()
        await db.refresh(conversation)
        return conversation
    except IntegrityError:
        await db.rollback()
        existing = await get_conversation_by_dy_id(db, account_id, user_id, remote_uid)
        if existing is None:
            raise
        return existing


async def get_conversation(db: AsyncSession, conv_id: str, user_id: str | None = None) -> IMConversation | None:
    q = select(IMConversation).where(IMConversation.id == conv_id)
    if user_id:
        q = q.where(IMConversation.user_id == user_id)
    res = await db.execute(q)
    return res.scalar_one_or_none()


async def get_conversation_by_dy_id(
    db: AsyncSession, account_id: str, user_id: str, remote_uid: str
) -> IMConversation | None:
    res = await db.execute(
        select(IMConversation).where(
            IMConversation.account_id == account_id,
            IMConversation.user_id == user_id,
            IMConversation.remote_uid == remote_uid,
        )
    )
    return res.scalar_one_or_none()


async def list_conversations(
    db: AsyncSession,
    user_id: str,
    page: int = 1,
    page_size: int = 20,
    search: str = "",
    account_id: str = "",
) -> tuple[list[IMConversation], int]:
    conditions = [IMConversation.user_id == user_id]
    if account_id:
        conditions.append(IMConversation.account_id == account_id)
    if search:
        pattern = f"%{search}%"
        matching_message = exists(
            select(IMMessage.id).where(
                IMMessage.conversation_id == IMConversation.id,
                IMMessage.user_id == user_id,
                IMMessage.content.ilike(pattern),
            )
        )
        conditions.append(
            or_(
                IMConversation.remote_nickname.ilike(pattern),
                IMConversation.remote_uid.ilike(pattern),
                matching_message,
            )
        )
    base = select(IMConversation).where(*conditions)
    count_res = await db.execute(select(func.count()).select_from(base.subquery()))
    total = count_res.scalar() or 0
    res = await db.execute(
        base.order_by(IMConversation.last_message_at.desc(), IMConversation.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(res.scalars().all()), total


async def save_conversation(db: AsyncSession, conv: IMConversation) -> None:
    await db.commit()
    await db.refresh(conv)


# ---- 消息 ----


async def create_message(db: AsyncSession, **fields) -> IMMessage:
    m = IMMessage(**fields)
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


async def get_message(db: AsyncSession, message_id: str, user_id: str) -> IMMessage | None:
    result = await db.execute(
        select(IMMessage).where(
            IMMessage.id == message_id,
            IMMessage.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def get_message_by_id(db: AsyncSession, message_id: str) -> IMMessage | None:
    return (await db.execute(select(IMMessage).where(IMMessage.id == message_id))).scalar_one_or_none()


async def save_message(db: AsyncSession, message: IMMessage) -> None:
    await db.commit()
    await db.refresh(message)


async def claim_scheduled_message(db: AsyncSession, message_id: str, user_id: str) -> bool:
    """Atomically claim one delayed reply before the external provider call."""
    result = await db.execute(
        update(IMMessage)
        .where(
            IMMessage.id == message_id,
            IMMessage.user_id == user_id,
            IMMessage.send_status == "scheduled",
            IMMessage.manual_takeover.is_(False),
        )
        .values(send_status="pending", send_error="")
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return int(getattr(result, "rowcount", 0) or 0) == 1


async def claim_failed_message_for_retry(db: AsyncSession, message_id: str, user_id: str) -> bool:
    """Atomically reserve one failed message and increment its retry count once."""
    result = await db.execute(
        update(IMMessage)
        .where(
            IMMessage.id == message_id,
            IMMessage.user_id == user_id,
            IMMessage.send_status == "failed",
            IMMessage.manual_takeover.is_(False),
        )
        .values(
            send_status="pending",
            send_error="",
            retry_count=IMMessage.retry_count + 1,
        )
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return int(getattr(result, "rowcount", 0) or 0) == 1


async def list_messages(
    db: AsyncSession,
    conversation_id: str,
    user_id: str,
    page: int = 1,
    page_size: int = 50,
    search: str = "",
) -> tuple[list[IMMessage], int]:
    conditions = [
        IMMessage.conversation_id == conversation_id,
        IMMessage.user_id == user_id,
    ]
    if search:
        conditions.append(IMMessage.content.ilike(f"%{search}%"))
    base = select(IMMessage).where(*conditions)
    count_res = await db.execute(select(func.count()).select_from(base.subquery()))
    total = count_res.scalar() or 0
    res = await db.execute(
        base.order_by(IMMessage.created_at.desc(), IMMessage.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(res.scalars().all()), total


async def cleanup_history(
    db: AsyncSession,
    *,
    cutoff: datetime,
    batch_size: int = 1000,
    max_batches: int = 10,
) -> tuple[int, int]:
    """Delete expired terminal history in bounded batches; never remove sendable work."""
    deleted_messages = 0
    protected_statuses = ("scheduled", "pending", "failed")
    for _ in range(max_batches):
        message_ids = (
            select(IMMessage.id)
            .where(
                IMMessage.created_at < cutoff,
                IMMessage.send_status.not_in(protected_statuses),
            )
            .order_by(IMMessage.created_at.asc(), IMMessage.id.asc())
            .limit(batch_size)
        )
        result = await db.execute(delete(IMMessage).where(IMMessage.id.in_(message_ids)))
        batch_count = int(getattr(result, "rowcount", 0) or 0)
        await db.commit()
        deleted_messages += batch_count
        if batch_count < batch_size:
            break

    deleted_conversations = 0
    for _ in range(max_batches):
        has_messages = exists(select(IMMessage.id).where(IMMessage.conversation_id == IMConversation.id))
        conversation_ids = (
            select(IMConversation.id)
            .where(
                IMConversation.last_message_at < cutoff,
                ~has_messages,
            )
            .order_by(IMConversation.last_message_at.asc(), IMConversation.id.asc())
            .limit(batch_size)
        )
        result = await db.execute(delete(IMConversation).where(IMConversation.id.in_(conversation_ids)))
        batch_count = int(getattr(result, "rowcount", 0) or 0)
        await db.commit()
        deleted_conversations += batch_count
        if batch_count < batch_size:
            break
    return deleted_messages, deleted_conversations


async def cleanup_metric_events(
    db: AsyncSession,
    *,
    cutoff: datetime,
    batch_size: int = 1000,
    max_batches: int = 10,
) -> int:
    """Delete expired rollout metrics in bounded batches."""
    deleted_events = 0
    for _ in range(max_batches):
        event_ids = (
            select(IMMetricEvent.id)
            .where(IMMetricEvent.created_at < cutoff)
            .order_by(IMMetricEvent.created_at.asc(), IMMetricEvent.id.asc())
            .limit(batch_size)
        )
        result = await db.execute(delete(IMMetricEvent).where(IMMetricEvent.id.in_(event_ids)))
        batch_count = int(getattr(result, "rowcount", 0) or 0)
        await db.commit()
        deleted_events += batch_count
        if batch_count < batch_size:
            break
    return deleted_events


async def get_message_by_remote_key(
    db: AsyncSession,
    conversation_id: str,
    user_id: str,
    direction: str,
    remote_message_id: str | None,
    remote_index: int | None,
) -> IMMessage | None:
    key_conditions = []
    if remote_message_id:
        key_conditions.append(IMMessage.remote_message_id == remote_message_id)
    if remote_index is not None:
        key_conditions.append(
            and_(
                IMMessage.direction == direction,
                IMMessage.remote_index == remote_index,
            )
        )
    if not key_conditions:
        return None
    query = select(IMMessage).where(
        IMMessage.conversation_id == conversation_id,
        IMMessage.user_id == user_id,
        or_(*key_conditions),
    )
    return (await db.execute(query)).scalar_one_or_none()


async def create_remote_message(
    db: AsyncSession,
    *,
    remote_message_id: str | None,
    remote_index: int | None,
    **fields,
) -> tuple[IMMessage, bool]:
    existing = await get_message_by_remote_key(
        db,
        fields["conversation_id"],
        fields["user_id"],
        fields["direction"],
        remote_message_id,
        remote_index,
    )
    if existing is not None:
        return existing, False

    message = IMMessage(
        remote_message_id=remote_message_id or None,
        remote_index=remote_index,
        **fields,
    )
    db.add(message)
    try:
        await db.commit()
        await db.refresh(message)
        return message, True
    except IntegrityError:
        await db.rollback()
        existing = await get_message_by_remote_key(
            db,
            fields["conversation_id"],
            fields["user_id"],
            fields["direction"],
            remote_message_id,
            remote_index,
        )
        if existing is None:
            raise
        return existing, False


# ---- 自动回复规则 ----


async def create_rule(db: AsyncSession, **fields) -> IMAutoReplyRule:
    r = IMAutoReplyRule(**fields)
    db.add(r)
    await db.commit()
    await db.refresh(r)
    return r


async def get_rule(db: AsyncSession, rule_id: str, user_id: str | None = None) -> IMAutoReplyRule | None:
    q = select(IMAutoReplyRule).where(IMAutoReplyRule.id == rule_id)
    if user_id:
        q = q.where(IMAutoReplyRule.user_id == user_id)
    res = await db.execute(q)
    return res.scalar_one_or_none()


async def list_rules(db: AsyncSession, user_id: str) -> list[IMAutoReplyRule]:
    res = await db.execute(
        select(IMAutoReplyRule).where(IMAutoReplyRule.user_id == user_id).order_by(IMAutoReplyRule.priority.asc())
    )
    return list(res.scalars().all())


async def get_active_rules(db: AsyncSession, user_id: str, account_id: str) -> list[IMAutoReplyRule]:
    """获取某账号适用的启用规则（账号专属 + 全局），按优先级排序"""
    res = await db.execute(
        select(IMAutoReplyRule)
        .where(
            IMAutoReplyRule.user_id == user_id,
            IMAutoReplyRule.enabled == True,  # noqa: E712
            (IMAutoReplyRule.account_id == account_id) | (IMAutoReplyRule.account_id == ""),
        )
        .order_by(IMAutoReplyRule.priority.asc())
    )
    return list(res.scalars().all())


async def save_rule(db: AsyncSession, rule: IMAutoReplyRule) -> None:
    await db.commit()
    await db.refresh(rule)


async def delete_rule(db: AsyncSession, rule: IMAutoReplyRule) -> None:
    await db.delete(rule)
    await db.commit()


# ---- 监听状态 ----


async def get_listener_state(db: AsyncSession, account_id: str, user_id: str) -> IMListenerState | None:
    res = await db.execute(
        select(IMListenerState).where(
            IMListenerState.account_id == account_id,
            IMListenerState.user_id == user_id,
        )
    )
    return res.scalar_one_or_none()


async def upsert_listener_state(db: AsyncSession, account_id: str, user_id: str, **fields) -> IMListenerState:
    state = await get_listener_state(db, account_id, user_id)
    if state is None:
        existing = (
            await db.execute(select(IMListenerState).where(IMListenerState.account_id == account_id))
        ).scalar_one_or_none()
        if existing is None:
            state = IMListenerState(account_id=account_id, user_id=user_id, **fields)
            db.add(state)
        else:
            if existing.user_id != user_id:
                raise ListenerOwnershipConflict(f"listener state for account {account_id} belongs to another user")
            state = existing
            for k, v in fields.items():
                setattr(state, k, v)
    else:
        for k, v in fields.items():
            setattr(state, k, v)
    await db.commit()
    await db.refresh(state)
    return state


async def list_listener_states(db: AsyncSession, user_id: str) -> list[IMListenerState]:
    res = await db.execute(
        select(IMListenerState)
        .join(
            PublishAccount,
            and_(
                PublishAccount.id == IMListenerState.account_id,
                PublishAccount.user_id == IMListenerState.user_id,
            ),
        )
        .where(IMListenerState.user_id == user_id)
    )
    return list(res.scalars().all())


# ---- 自动发送授权与 Kill Switch ----


async def get_automation_consent(
    db: AsyncSession, account_id: str, user_id: str
) -> IMAutomationConsent | None:
    return (
        await db.execute(
            select(IMAutomationConsent).where(
                IMAutomationConsent.account_id == account_id,
                IMAutomationConsent.user_id == user_id,
            )
        )
    ).scalar_one_or_none()


async def list_automation_consents(db: AsyncSession, user_id: str) -> list[IMAutomationConsent]:
    result = await db.execute(
        select(IMAutomationConsent)
        .join(
            PublishAccount,
            and_(
                PublishAccount.id == IMAutomationConsent.account_id,
                PublishAccount.user_id == IMAutomationConsent.user_id,
            ),
        )
        .where(IMAutomationConsent.user_id == user_id)
    )
    return list(result.scalars().all())


async def upsert_automation_consent(
    db: AsyncSession,
    account_id: str,
    user_id: str,
    risk_version: str,
    *,
    enabled: bool,
) -> IMAutomationConsent:
    consent = await get_automation_consent(db, account_id, user_id)
    if consent is None:
        existing = (
            await db.execute(select(IMAutomationConsent).where(IMAutomationConsent.account_id == account_id))
        ).scalar_one_or_none()
        if existing is not None:
            raise ListenerOwnershipConflict(f"automation consent for account {account_id} belongs to another user")
        consent = IMAutomationConsent(
            account_id=account_id,
            user_id=user_id,
            risk_version=risk_version,
            auto_reply_enabled=enabled,
            accepted_at=datetime.now(UTC),
        )
        db.add(consent)
    else:
        consent.risk_version = risk_version
        consent.auto_reply_enabled = enabled
        consent.accepted_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(consent)
    return consent


async def get_global_control(db: AsyncSession) -> IMGlobalControl | None:
    return await db.get(IMGlobalControl, "global")


async def automation_block_reason(db: AsyncSession, account_id: str, user_id: str) -> str | None:
    consent = await get_automation_consent(db, account_id, user_id)
    if consent is None or not consent.auto_reply_enabled:
        return "AutomationNotAuthorized"
    control = await get_global_control(db)
    if control is None or control.stopped:
        return "GlobalKillSwitch"
    from app.core.config import get_settings

    if get_settings().im_gray_enforced and not await is_gray_account_enabled(db, account_id, user_id):
        return "GrayApprovalRequired"
    return None


async def set_global_kill_switch(db: AsyncSession, *, stopped: bool) -> int:
    control = await get_global_control(db)
    if control is None:
        control = IMGlobalControl(id="global", stopped=stopped, updated_at=datetime.now(UTC))
        db.add(control)
    else:
        control.stopped = stopped
        control.updated_at = datetime.now(UTC)

    canceled = 0
    if stopped:
        result = await db.execute(
            update(IMMessage)
            .where(IMMessage.send_status == "scheduled")
            .values(send_status="canceled", send_error="GlobalKillSwitch")
        )
        canceled = int(getattr(result, "rowcount", 0) or 0)
    await db.commit()
    return canceled


async def disable_account_automation(
    db: AsyncSession,
    account_id: str,
    user_id: str,
    *,
    reason: str = "AccountKillSwitch",
) -> int:
    consent = await get_automation_consent(db, account_id, user_id)
    if consent is not None:
        consent.auto_reply_enabled = False
    conversation_ids = select(IMConversation.id).where(
        IMConversation.account_id == account_id,
        IMConversation.user_id == user_id,
    )
    result = await db.execute(
        update(IMMessage)
        .where(
            IMMessage.conversation_id.in_(conversation_ids),
            IMMessage.send_status == "scheduled",
        )
        .values(send_status="canceled", send_error=reason[:256])
    )
    await db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


# ---- 灰度与监控 ----


async def is_gray_account_enabled(db: AsyncSession, account_id: str, user_id: str) -> bool:
    result = await db.execute(
        select(IMGrayAccount.id).where(
            IMGrayAccount.account_id == account_id,
            IMGrayAccount.user_id == user_id,
            IMGrayAccount.enabled.is_(True),
        )
    )
    return result.scalar_one_or_none() is not None


async def approve_gray_account(db: AsyncSession, account_id: str, *, approved_by: str) -> IMGrayAccount | None:
    account = await db.get(PublishAccount, account_id)
    if account is None:
        return None
    gray = (
        await db.execute(select(IMGrayAccount).where(IMGrayAccount.account_id == account_id))
    ).scalar_one_or_none()
    if gray is None:
        gray = IMGrayAccount(
            account_id=account_id,
            user_id=account.user_id,
            approved_by=approved_by,
            enabled=True,
        )
        db.add(gray)
    else:
        gray.user_id = account.user_id
        gray.approved_by = approved_by
        gray.enabled = True
        gray.created_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(gray)
    return gray


async def remove_gray_account(db: AsyncSession, account_id: str) -> bool:
    result = await db.execute(
        update(IMGrayAccount)
        .where(IMGrayAccount.account_id == account_id, IMGrayAccount.enabled.is_(True))
        .values(enabled=False)
    )
    await db.commit()
    return int(getattr(result, "rowcount", 0) or 0) == 1


async def list_gray_accounts(db: AsyncSession) -> list[tuple[IMGrayAccount, PublishAccount]]:
    result = await db.execute(
        select(IMGrayAccount, PublishAccount)
        .join(PublishAccount, PublishAccount.id == IMGrayAccount.account_id)
        .where(
            IMGrayAccount.enabled.is_(True),
            PublishAccount.user_id == IMGrayAccount.user_id,
        )
        .order_by(IMGrayAccount.created_at.desc())
    )
    return [(row[0], row[1]) for row in result.all()]


async def gray_account_count(db: AsyncSession) -> int:
    result = await db.execute(select(func.count(IMGrayAccount.id)).where(IMGrayAccount.enabled.is_(True)))
    return int(result.scalar() or 0)


async def record_metric_event(
    db: AsyncSession,
    *,
    kind: str,
    account_id: str = "",
    user_id: str = "",
    detail: str = "",
) -> None:
    db.add(
        IMMetricEvent(
            kind=kind[:48],
            account_id=account_id[:32],
            user_id=user_id[:32],
            detail=detail[:256],
        )
    )
    await db.commit()


async def metric_counts_since(db: AsyncSession, since: datetime) -> dict[str, int]:
    result = await db.execute(
        select(IMMetricEvent.kind, func.count(IMMetricEvent.id))
        .where(IMMetricEvent.created_at >= since)
        .group_by(IMMetricEvent.kind)
    )
    return {str(kind): int(count) for kind, count in result.all()}


async def gray_and_listener_counts(db: AsyncSession) -> tuple[int, int, int]:
    gray = int(
        (
            await db.execute(
                select(func.count(IMGrayAccount.id))
                .join(
                    PublishAccount,
                    and_(
                        PublishAccount.id == IMGrayAccount.account_id,
                        PublishAccount.user_id == IMGrayAccount.user_id,
                    ),
                )
                .where(IMGrayAccount.enabled.is_(True), PublishAccount.status == "active")
            )
        ).scalar()
        or 0
    )
    listener_scope = (
        select(IMListenerState.id)
        .join(
            IMGrayAccount,
            and_(
                IMGrayAccount.account_id == IMListenerState.account_id,
                IMGrayAccount.user_id == IMListenerState.user_id,
            ),
        )
        .join(
            PublishAccount,
            and_(
                PublishAccount.id == IMListenerState.account_id,
                PublishAccount.user_id == IMListenerState.user_id,
            ),
        )
        .where(IMGrayAccount.enabled.is_(True), PublishAccount.status == "active")
    )
    listeners = int(
        (await db.execute(select(func.count()).select_from(listener_scope.subquery()))).scalar() or 0
    )
    listening = int(
        (
            await db.execute(
                select(func.count()).select_from(
                    listener_scope.where(IMListenerState.status == "listening").subquery()
                )
            )
        ).scalar()
        or 0
    )
    return gray, listeners, listening
