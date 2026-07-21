"""im 模块数据访问层"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import IMAutoReplyRule, IMConversation, IMListenerState, IMMessage

# ---- 会话 ----


async def create_conversation(db: AsyncSession, **fields) -> IMConversation:
    c = IMConversation(**fields)
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


async def get_conversation(db: AsyncSession, conv_id: str, user_id: str | None = None) -> IMConversation | None:
    q = select(IMConversation).where(IMConversation.id == conv_id)
    if user_id:
        q = q.where(IMConversation.user_id == user_id)
    res = await db.execute(q)
    return res.scalar_one_or_none()


async def get_conversation_by_dy_id(db: AsyncSession, account_id: str, remote_uid: str) -> IMConversation | None:
    res = await db.execute(
        select(IMConversation).where(IMConversation.account_id == account_id, IMConversation.remote_uid == remote_uid)
    )
    return res.scalar_one_or_none()


async def find_remote_conversation(
    db: AsyncSession,
    account_id: str,
    remote_uid: str,
    dy_conversation_id: str = "",
) -> IMConversation | None:
    if dy_conversation_id:
        res = await db.execute(
            select(IMConversation).where(
                IMConversation.account_id == account_id,
                IMConversation.dy_conversation_id == dy_conversation_id,
            )
        )
        if conversation := res.scalar_one_or_none():
            return conversation
    return await get_conversation_by_dy_id(db, account_id, remote_uid)


async def list_conversations(
    db: AsyncSession, user_id: str, page: int = 1, page_size: int = 20
) -> tuple[list[IMConversation], int]:
    base = select(IMConversation).where(
        IMConversation.user_id == user_id,
        IMConversation.dy_ticket != "mock_ticket",
    )
    count_res = await db.execute(select(func.count()).select_from(base.subquery()))
    total = count_res.scalar() or 0
    res = await db.execute(
        base.order_by(IMConversation.last_message_at.desc()).offset((page - 1) * page_size).limit(page_size)
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


async def get_message_by_remote_key(
    db: AsyncSession,
    conversation_id: str,
    direction: str,
    remote_message_id: str | None,
    remote_index: int | None,
) -> IMMessage | None:
    if remote_message_id:
        res = await db.execute(
            select(IMMessage).where(
                IMMessage.conversation_id == conversation_id,
                IMMessage.remote_message_id == remote_message_id,
            )
        )
        if message := res.scalar_one_or_none():
            return message
    if remote_index is not None:
        res = await db.execute(
            select(IMMessage).where(
                IMMessage.conversation_id == conversation_id,
                IMMessage.direction == direction,
                IMMessage.remote_index == remote_index,
            )
        )
        return res.scalar_one_or_none()
    return None


async def get_unkeyed_outgoing_message(
    db: AsyncSession,
    conversation_id: str,
    content: str,
) -> IMMessage | None:
    res = await db.execute(
        select(IMMessage)
        .where(
            IMMessage.conversation_id == conversation_id,
            IMMessage.direction == "out",
            IMMessage.remote_message_id.is_(None),
            IMMessage.content == content,
            IMMessage.created_at >= datetime.now(UTC) - timedelta(minutes=10),
        )
        .order_by(IMMessage.created_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def save_message(db: AsyncSession, message: IMMessage) -> None:
    await db.commit()
    await db.refresh(message)


async def list_messages(
    db: AsyncSession, conversation_id: str, page: int = 1, page_size: int = 50
) -> tuple[list[IMMessage], int]:
    base = select(IMMessage).where(IMMessage.conversation_id == conversation_id)
    count_res = await db.execute(select(func.count()).select_from(base.subquery()))
    total = count_res.scalar() or 0
    res = await db.execute(base.order_by(IMMessage.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return list(res.scalars().all()), total


async def count_today_replies(db: AsyncSession, user_id: str, rule_id: str) -> int:
    """统计某规则今日已自动回复数（#6: 按 rule_id 过滤）"""
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    res = await db.execute(
        select(func.count()).where(
            IMMessage.user_id == user_id,
            IMMessage.direction == "out",
            IMMessage.auto_replied == True,  # noqa: E712
            IMMessage.rule_id == rule_id,
            IMMessage.created_at >= today_start,
        )
    )
    return res.scalar() or 0


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


async def get_listener_state(db: AsyncSession, account_id: str) -> IMListenerState | None:
    res = await db.execute(select(IMListenerState).where(IMListenerState.account_id == account_id))
    return res.scalar_one_or_none()


async def upsert_listener_state(db: AsyncSession, account_id: str, user_id: str, **fields) -> IMListenerState:
    state = await get_listener_state(db, account_id)
    if state is None:
        state = IMListenerState(account_id=account_id, user_id=user_id, **fields)
        db.add(state)
    else:
        for k, v in fields.items():
            setattr(state, k, v)
    await db.commit()
    await db.refresh(state)
    return state


async def list_listener_states(db: AsyncSession, user_id: str) -> list[IMListenerState]:
    res = await db.execute(select(IMListenerState).where(IMListenerState.user_id == user_id))
    return list(res.scalars().all())
