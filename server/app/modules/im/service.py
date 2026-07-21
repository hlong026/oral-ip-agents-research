"""im 业务编排（私信收发 + 自动回复策略引擎）"""

import asyncio
import json
import logging
import random
import re
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionLocal
from app.core.events import publish as emit
from app.providers.registry import registry

from . import repository as repo
from .events import CHANNEL_IM, EV_AUTO_REPLIED, EV_LISTENER_STATUS, EV_NEW_MESSAGE
from .models import IMAutoReplyRule, IMConversation, IMMessage
from .schemas import (
    ConversationOut,
    ConversationPageOut,
    ListenerControlIn,
    ListenerStatusOut,
    MessageOut,
    MessagePageOut,
    RuleCreateIn,
    RuleOut,
    RuleUpdateIn,
    SendMessageIn,
)

logger = logging.getLogger(__name__)

# #13 每分钟频率限制：account_id → 最近 60s 内发送时间戳
_rate_window: dict[str, deque] = defaultdict(lambda: deque(maxlen=10))
MAX_REPLIES_PER_MINUTE = 3


# ============ 转换函数 ============


def conv_to_out(c: IMConversation) -> ConversationOut:
    return ConversationOut(
        id=c.id,
        accountId=c.account_id,
        platform=c.platform,
        remoteUid=c.remote_uid,
        remoteNickname=c.remote_nickname,
        remoteAvatar=c.remote_avatar,
        lastMessageAt=c.last_message_at.astimezone(UTC).isoformat() if c.last_message_at else "",
        unreadCount=c.unread_count,
        status=c.status,
        createdAt=c.created_at.astimezone(UTC).isoformat(),
    )


def msg_to_out(m: IMMessage) -> MessageOut:
    return MessageOut(
        id=m.id,
        conversationId=m.conversation_id,
        direction=m.direction,
        msgType=m.msg_type,
        content=m.content,
        autoReplied=m.auto_replied,
        replyContent=m.reply_content,
        createdAt=m.created_at.astimezone(UTC).isoformat(),
    )


def rule_to_out(r: IMAutoReplyRule) -> RuleOut:
    return RuleOut(
        id=r.id,
        accountId=r.account_id,
        name=r.name,
        triggerType=r.trigger_type,
        triggerPattern=r.trigger_pattern,
        replyMode=r.reply_mode,
        replyTemplate=r.reply_template,
        llmPrompt=r.llm_prompt,
        priority=r.priority,
        dailyLimit=r.daily_limit,
        delayMin=r.delay_min,
        delayMax=r.delay_max,
        enabled=r.enabled,
        createdAt=r.created_at.astimezone(UTC).isoformat(),
    )


# ============ 会话管理 ============


async def list_conversations(db: AsyncSession, user_id: str, page: int = 1, page_size: int = 20) -> ConversationPageOut:
    items, total = await repo.list_conversations(db, user_id, page, page_size)
    return ConversationPageOut(items=[conv_to_out(c) for c in items], total=total, page=page, pageSize=page_size)


async def list_messages(
    db: AsyncSession, user_id: str, conversation_id: str, page: int = 1, page_size: int = 50
) -> MessagePageOut:
    conv = await repo.get_conversation(db, conversation_id, user_id)
    if not conv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "会话不存在"})
    items, total = await repo.list_messages(db, conversation_id, page, page_size)
    return MessagePageOut(items=[msg_to_out(m) for m in items], total=total, page=page, pageSize=page_size)


async def send_message(db: AsyncSession, user_id: str, conversation_id: str, inp: SendMessageIn) -> MessageOut:
    conv = await repo.get_conversation(db, conversation_id, user_id)
    if not conv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "会话不存在"})
    # 通过 Provider 发送
    im_provider = registry.im_driver(conv.platform)
    content_json = json.dumps({"text": inp.content}, ensure_ascii=False)
    session = await _load_account_session(conv.account_id, user_id)
    await im_provider.send_message(
        session=session,
        conversation_id=conv.dy_conversation_id,
        conversation_short_id=conv.dy_conversation_short_id,
        ticket=conv.dy_ticket,
        content=inp.content,
    )
    # 落库
    msg = await repo.create_message(
        db, conversation_id=conv.id, user_id=user_id, direction="out", msg_type=inp.msgType, content=content_json
    )
    conv.last_message_at = datetime.now(UTC)
    await repo.save_conversation(db, conv)
    return msg_to_out(msg)


async def mark_read(db: AsyncSession, user_id: str, conversation_id: str) -> None:
    conv = await repo.get_conversation(db, conversation_id, user_id)
    if not conv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "会话不存在"})
    conv.unread_count = 0
    await repo.save_conversation(db, conv)


# ============ 自动回复规则 CRUD ============


async def list_rules(db: AsyncSession, user_id: str) -> list[RuleOut]:
    rules = await repo.list_rules(db, user_id)
    return [rule_to_out(r) for r in rules]


async def create_rule(db: AsyncSession, user_id: str, inp: RuleCreateIn) -> RuleOut:
    rule = await repo.create_rule(
        db,
        user_id=user_id,
        account_id=inp.accountId,
        name=inp.name,
        trigger_type=inp.triggerType,
        trigger_pattern=inp.triggerPattern,
        reply_mode=inp.replyMode,
        reply_template=inp.replyTemplate,
        llm_prompt=inp.llmPrompt,
        priority=inp.priority,
        daily_limit=inp.dailyLimit,
        delay_min=inp.delayMin,
        delay_max=inp.delayMax,
        enabled=inp.enabled,
    )
    return rule_to_out(rule)


async def update_rule(db: AsyncSession, user_id: str, rule_id: str, inp: RuleUpdateIn) -> RuleOut:
    rule = await repo.get_rule(db, rule_id, user_id)
    if not rule:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "规则不存在"})
    updates = inp.model_dump(exclude_none=True)
    field_map = {
        "name": "name",
        "triggerType": "trigger_type",
        "triggerPattern": "trigger_pattern",
        "replyMode": "reply_mode",
        "replyTemplate": "reply_template",
        "llmPrompt": "llm_prompt",
        "priority": "priority",
        "dailyLimit": "daily_limit",
        "delayMin": "delay_min",
        "delayMax": "delay_max",
        "enabled": "enabled",
    }
    for k, v in updates.items():
        attr = field_map.get(k, k)
        setattr(rule, attr, v)
    await repo.save_rule(db, rule)
    return rule_to_out(rule)


async def delete_rule(db: AsyncSession, user_id: str, rule_id: str) -> None:
    rule = await repo.get_rule(db, rule_id, user_id)
    if not rule:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "规则不存在"})
    await repo.delete_rule(db, rule)


async def toggle_rule(db: AsyncSession, user_id: str, rule_id: str) -> RuleOut:
    rule = await repo.get_rule(db, rule_id, user_id)
    if not rule:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "规则不存在"})
    rule.enabled = not rule.enabled
    await repo.save_rule(db, rule)
    return rule_to_out(rule)


# ============ 监听控制 ============


async def get_listener_status(db: AsyncSession, user_id: str) -> list[ListenerStatusOut]:
    states = await repo.list_listener_states(db, user_id)
    result = []
    for s in states:
        result.append(
            ListenerStatusOut(
                accountId=s.account_id,
                platform="douyin",
                status=s.status,
                lastHeartbeat=s.last_heartbeat.astimezone(UTC).isoformat() if s.last_heartbeat else None,
                errorMsg=s.error_msg,
                startedAt=s.started_at.astimezone(UTC).isoformat() if s.started_at else None,
            )
        )
    return result


async def start_listener(db: AsyncSession, user_id: str, inp: ListenerControlIn) -> ListenerStatusOut:
    """Persist listener intent; the independent supervisor owns the connection."""
    await _require_owned_account(db, user_id, inp.accountId)

    await repo.upsert_listener_state(
        db, account_id=inp.accountId, user_id=user_id, status="listening", started_at=datetime.now(UTC), error_msg=""
    )
    await emit(
        CHANNEL_IM, {"kind": EV_LISTENER_STATUS, "userId": user_id, "accountId": inp.accountId, "status": "listening"}
    )
    return ListenerStatusOut(accountId=inp.accountId, status="listening")


async def stop_listener(db: AsyncSession, user_id: str, inp: ListenerControlIn) -> ListenerStatusOut:
    """Persist stop intent; the independent supervisor observes and closes the connection."""
    await _require_owned_account(db, user_id, inp.accountId)

    await repo.upsert_listener_state(db, account_id=inp.accountId, user_id=user_id, status="disconnected", error_msg="")
    await emit(
        CHANNEL_IM,
        {"kind": EV_LISTENER_STATUS, "userId": user_id, "accountId": inp.accountId, "status": "disconnected"},
    )
    return ListenerStatusOut(accountId=inp.accountId, status="disconnected")


# ============ 消息接收处理（供 Worker 调用） ============


async def handle_incoming_message(
    account_id: str,
    user_id: str,
    remote_uid: str,
    remote_nickname: str,
    remote_avatar: str,
    msg_type: int,
    content: str,
    dy_conversation_id: str = "",
    dy_conversation_short_id: str = "",
    dy_ticket: str = "",
) -> None:
    """Worker 收到新私信后的统一入口：落库 → 推送 → 触发自动回复"""
    async with _session() as db:
        # 1. 查找或创建会话
        conv = await repo.get_conversation_by_dy_id(db, account_id, remote_uid)
        if conv is None:
            conv = await repo.create_conversation(
                db,
                account_id=account_id,
                user_id=user_id,
                platform="douyin",
                remote_uid=remote_uid,
                remote_nickname=remote_nickname,
                remote_avatar=remote_avatar,
                dy_conversation_id=dy_conversation_id,
                dy_conversation_short_id=dy_conversation_short_id,
                dy_ticket=dy_ticket,
                last_message_at=datetime.now(UTC),
                unread_count=1,
            )
        else:
            conv.last_message_at = datetime.now(UTC)
            conv.unread_count = (conv.unread_count or 0) + 1
            if remote_nickname:
                conv.remote_nickname = remote_nickname
            await repo.save_conversation(db, conv)

        # 2. 消息落库
        content_json = json.dumps({"text": content}, ensure_ascii=False) if msg_type == 7 else content
        msg = await repo.create_message(
            db, conversation_id=conv.id, user_id=user_id, direction="in", msg_type=msg_type, content=content_json
        )

        # 3. 推送前端
        await emit(
            CHANNEL_IM,
            {
                "kind": EV_NEW_MESSAGE,
                "userId": user_id,
                "conversationId": conv.id,
                "message": msg_to_out(msg).model_dump(),
            },
        )

        # 4. 触发自动回复（仅文本消息）
        if msg_type == 7:
            await _try_auto_reply(db, conv, content)


async def _try_auto_reply(db: AsyncSession, conv: IMConversation, text: str) -> None:
    """自动回复策略引擎（#4: 延迟发送拆分为独立 Task，不持有 DB Session）"""
    rules = await repo.get_active_rules(db, conv.user_id, conv.account_id)
    if not rules:
        return

    matched_rule = _match_rule(rules, text)
    if matched_rule is None:
        return

    # #6 检查每日限额（按 rule_id 过滤）
    today_count = await repo.count_today_replies(db, conv.user_id, matched_rule.id)
    if today_count >= matched_rule.daily_limit:
        logger.info(f"rule {matched_rule.id} daily limit reached ({today_count})")
        return

    # #13 每分钟频率限制
    if _is_rate_limited(conv.account_id):
        logger.info(f"account {conv.account_id[:8]} rate limited (>{MAX_REPLIES_PER_MINUTE}/min)")
        return

    # 生成回复内容
    reply_text = await _generate_reply(db, matched_rule, text, conv)
    if not reply_text:
        return

    # #4 拆分为独立 Task：延迟 + 发送 + 落库（不占用当前 DB Session）
    delay = random.uniform(max(0, matched_rule.delay_min), max(matched_rule.delay_min, matched_rule.delay_max))
    asyncio.create_task(
        _delayed_reply(
            account_id=conv.account_id,
            user_id=conv.user_id,
            conversation_id=conv.id,
            platform=conv.platform,
            dy_conversation_id=conv.dy_conversation_id,
            dy_conversation_short_id=conv.dy_conversation_short_id,
            dy_ticket=conv.dy_ticket,
            reply_text=reply_text,
            rule_id=matched_rule.id,
            delay=delay,
        )
    )


async def _delayed_reply(
    *,
    account_id: str,
    user_id: str,
    conversation_id: str,
    platform: str,
    dy_conversation_id: str,
    dy_conversation_short_id: str,
    dy_ticket: str,
    reply_text: str,
    rule_id: str,
    delay: float,
) -> None:
    """#4 独立 Task：延迟后发送回复并落库"""
    await asyncio.sleep(delay)
    try:
        im_provider = registry.im_driver(platform)
        session = await _load_account_session(account_id, user_id)
        await im_provider.send_message(
            session=session,
            conversation_id=dy_conversation_id,
            conversation_short_id=dy_conversation_short_id,
            ticket=dy_ticket,
            content=reply_text,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"auto reply send failed: {e}")
        return

    # 记录频率
    _rate_window[account_id].append(time.time())

    # 落库（重新获取 Session）
    async with _session() as db:
        reply_msg = await repo.create_message(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
            direction="out",
            msg_type=7,
            content=json.dumps({"text": reply_text}, ensure_ascii=False),
            auto_replied=True,
            rule_id=rule_id,
        )
        conv = await repo.get_conversation(db, conversation_id)
        if conv:
            conv.last_message_at = datetime.now(UTC)
            await repo.save_conversation(db, conv)

    # 推送前端
    await emit(
        CHANNEL_IM,
        {
            "kind": EV_AUTO_REPLIED,
            "userId": user_id,
            "conversationId": conversation_id,
            "reply": reply_text,
            "messageId": reply_msg.id,
        },
    )


def _match_rule(rules: list[IMAutoReplyRule], text: str) -> IMAutoReplyRule | None:
    """#14 按优先级匹配规则：keyword 优先，all/llm 作为兜底"""
    fallback: IMAutoReplyRule | None = None
    for rule in rules:
        if rule.trigger_type == "keyword":
            pattern = rule.trigger_pattern.strip()
            if not pattern:
                continue
            try:
                if re.search(pattern, text, re.IGNORECASE):
                    return rule
            except re.error:
                if pattern in text:
                    return rule
        elif rule.trigger_type in ("all", "llm") and fallback is None:
            fallback = rule
    return fallback


async def _generate_reply(db: AsyncSession, rule: IMAutoReplyRule, incoming_text: str, conv: IMConversation) -> str:
    """根据规则模式生成回复（#5: 注入 IP 人设）"""
    if rule.reply_mode == "template":
        return rule.reply_template

    # LLM 模式：注入 IP 人设上下文
    try:
        llm = registry.get("llm")
        persona_ctx = await _get_persona_context(db, conv.user_id)
        base_prompt = rule.llm_prompt or "请简洁友好地回复用户的私信。"
        prompt = f"{persona_ctx}\n{base_prompt}" if persona_ctx else base_prompt
        reply = await llm.rewrite(text=incoming_text, intensity="light", prompt=prompt)
        return reply[:500]  # 限制长度
    except Exception as e:  # noqa: BLE001
        logger.warning(f"LLM reply generation failed: {e}")
        return rule.reply_template or ""


async def _get_persona_context(db: AsyncSession, user_id: str) -> str:
    """#5 从 ipasset 模块读取当前激活 IP 人设定义"""
    try:
        from app.modules.ipasset import repository as ip_repo
        from app.modules.ipasset import service as ip_service

        persona_id = await ip_service.get_active_persona_id(db, user_id)
        if not persona_id:
            return ""
        persona = await ip_repo.get(db, persona_id, user_id)
        if not persona:
            return ""
        return ip_service.persona_prompt_context(persona)
    except Exception:  # noqa: BLE001
        return ""


# ============ 辅助 ============


def _is_rate_limited(account_id: str) -> bool:
    """#13 滑动窗口限流：每分钟最多 MAX_REPLIES_PER_MINUTE 条"""
    now = time.time()
    window = _rate_window[account_id]
    # 清除 60s 前的记录
    while window and window[0] < now - 60:
        window.popleft()
    return len(window) >= MAX_REPLIES_PER_MINUTE


async def _load_account_session(account_id: str, user_id: str) -> dict:
    """#1 异步加载账号 session"""
    from app.modules.publish import repository as pub_repo

    async with SessionLocal() as db:
        acc = await pub_repo.get_account(db, account_id, user_id)
        if acc:
            return pub_repo.account_session(acc)
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "ACCOUNT_NOT_FOUND", "message": "发布账号不存在"},
        )


async def _require_owned_account(db: AsyncSession, user_id: str, account_id: str) -> None:
    from app.modules.publish import repository as pub_repo

    if not await pub_repo.get_account(db, account_id, user_id):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "ACCOUNT_NOT_FOUND", "message": "发布账号不存在"},
        )


@asynccontextmanager
async def _session():
    async with SessionLocal() as db:
        yield db
