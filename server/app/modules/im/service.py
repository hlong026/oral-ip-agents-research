"""im 业务编排（私信收发 + 自动回复策略引擎）"""

import json
import logging
import random
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.events import publish as emit
from app.modules.publish.models import PublishAccount
from app.providers.registry import registry

from . import repository as repo
from .events import CHANNEL_IM, EV_AUTO_REPLIED, EV_LISTENER_STATUS, EV_NEW_MESSAGE
from .models import IMAutoReplyRule, IMConversation, IMMessage
from .schemas import (
    AutomationConsentIn,
    AutomationStatusOut,
    ConversationOut,
    ConversationPageOut,
    GrayAccountOut,
    ListenerControlIn,
    ListenerStatusOut,
    MessageOut,
    MessagePageOut,
    MonitoringIncidentIn,
    MonitoringSummaryOut,
    RuleCreateIn,
    RuleOut,
    RuleUpdateIn,
    SendMessageIn,
)

logger = logging.getLogger(__name__)

MAX_REPLIES_PER_MINUTE = 3
MAX_REPLIES_PER_CONVERSATION_PER_DAY = 10
_reply_limiter = None
AUTOMATION_RISK_VERSION = "im-auto-reply-v1"


class AccountCredentialExpiredError(RuntimeError):
    """The platform session is known to be expired and must not be retried."""


class GrayAccountNotApprovedError(RuntimeError):
    """The account is outside the active rollout allowlist."""


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
        sendStatus=m.send_status,
        sendError=m.send_error,
        retryCount=m.retry_count,
        manualTakeover=m.manual_takeover,
        moderationStatus=m.moderation_status,
        moderationReason=m.moderation_reason,
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
        deliveryMode=r.delivery_mode,
        enabled=r.enabled,
        createdAt=r.created_at.astimezone(UTC).isoformat(),
    )


# ============ 会话管理 ============


async def list_conversations(
    db: AsyncSession,
    user_id: str,
    page: int = 1,
    page_size: int = 20,
    search: str = "",
    account_id: str = "",
) -> ConversationPageOut:
    items, total = await repo.list_conversations(
        db,
        user_id,
        page,
        page_size,
        search=search.strip(),
        account_id=account_id,
    )
    return ConversationPageOut(items=[conv_to_out(c) for c in items], total=total, page=page, pageSize=page_size)


async def list_messages(
    db: AsyncSession,
    user_id: str,
    conversation_id: str,
    page: int = 1,
    page_size: int = 50,
    search: str = "",
) -> MessagePageOut:
    conv = await repo.get_conversation(db, conversation_id, user_id)
    if not conv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "会话不存在"})
    items, total = await repo.list_messages(
        db,
        conversation_id,
        user_id,
        page,
        page_size,
        search=search.strip(),
    )
    return MessagePageOut(items=[msg_to_out(m) for m in items], total=total, page=page, pageSize=page_size)


async def send_message(db: AsyncSession, user_id: str, conversation_id: str, inp: SendMessageIn) -> MessageOut:
    conv = await repo.get_conversation(db, conversation_id, user_id)
    if not conv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "会话不存在"})
    await _require_gray_account(db, conv.account_id, user_id)
    from app.modules.im.moderation import review_outgoing

    moderation = review_outgoing(inp.content)
    if not moderation.allowed:
        await record_metric("moderation_blocked", account_id=conv.account_id, user_id=user_id)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "IM_CONTENT_BLOCKED", "message": moderation.reason_text},
        )
    content_json = json.dumps({"text": inp.content}, ensure_ascii=False)
    msg = await repo.create_message(
        db,
        conversation_id=conv.id,
        user_id=user_id,
        direction="out",
        msg_type=inp.msgType,
        content=content_json,
        send_status="pending",
        moderation_status="approved",
    )
    try:
        await _send_existing_message(db, conv, msg, inp.content)
        return msg_to_out(msg)
    except Exception as error:  # noqa: BLE001
        raise _send_failure(msg) from error


async def retry_message(db: AsyncSession, user_id: str, message_id: str) -> MessageOut:
    message = await repo.get_message(db, message_id, user_id)
    if message is None or message.direction != "out":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "消息不存在"})
    if message.manual_takeover or message.send_status == "manual":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "MANUAL_TAKEOVER", "message": "消息已转人工处理，不能自动重试"},
        )
    if message.send_status != "failed":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "MESSAGE_NOT_FAILED", "message": "只有发送失败的消息可以重试"},
        )
    conversation = await repo.get_conversation(db, message.conversation_id, user_id)
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "会话不存在"})
    await _require_gray_account(db, conversation.account_id, user_id)
    from app.modules.im.moderation import review_outgoing

    moderation = review_outgoing(_message_text(message))
    if not moderation.allowed:
        await record_metric("moderation_blocked", account_id=conversation.account_id, user_id=user_id)
        message.send_status = "blocked"
        message.moderation_status = "blocked"
        message.moderation_reason = moderation.reason_text
        await repo.save_message(db, message)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "IM_CONTENT_BLOCKED", "message": moderation.reason_text},
        )

    if not await repo.claim_failed_message_for_retry(db, message.id, user_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "MESSAGE_ALREADY_CLAIMED", "message": "消息已被其他任务接管"},
        )
    await db.refresh(message)
    try:
        await _send_existing_message(db, conversation, message, _message_text(message))
        return msg_to_out(message)
    except Exception as error:  # noqa: BLE001
        raise _send_failure(message) from error


async def take_over_message(db: AsyncSession, user_id: str, message_id: str) -> MessageOut:
    message = await repo.get_message(db, message_id, user_id)
    if message is None or message.direction != "out":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "消息不存在"})
    if message.send_status != "failed":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "MESSAGE_NOT_FAILED", "message": "只有发送失败的消息可以转人工处理"},
        )
    message.send_status = "manual"
    message.manual_takeover = True
    await repo.save_message(db, message)
    return msg_to_out(message)


async def _send_existing_message(
    db: AsyncSession,
    conversation: IMConversation,
    message: IMMessage,
    content: str,
) -> None:
    try:
        session = await _load_account_session(conversation.account_id, conversation.user_id)
        provider = registry.im_driver(conversation.platform)
        sent = await provider.send_message(
            session=session,
            conversation_id=conversation.dy_conversation_id,
            conversation_short_id=conversation.dy_conversation_short_id,
            ticket=conversation.dy_ticket,
            content=content,
        )
        if sent is not True:
            raise RuntimeError("平台未确认私信发送成功")
    except Exception as error:  # noqa: BLE001
        message.send_status = "failed"
        message.send_error = error.__class__.__name__[:256]
        await repo.save_message(db, message)
        logger.warning(
            "IM send failed: account=%s conversation=%s message=%s error=%s",
            conversation.account_id[:8],
            conversation.id[:8],
            message.id[:8],
            message.send_error,
        )
        await record_metric(
            "send_failure",
            account_id=conversation.account_id,
            user_id=conversation.user_id,
            detail=message.send_error,
        )
        raise

    message.send_status = "sent"
    message.send_error = ""
    await repo.save_message(db, message)
    conversation.last_message_at = datetime.now(UTC)
    await repo.save_conversation(db, conversation)
    await record_metric("send_success", account_id=conversation.account_id, user_id=conversation.user_id)


def _send_failure(message: IMMessage) -> HTTPException:
    if message.send_error == GrayAccountNotApprovedError.__name__:
        return HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={
                "code": "IM_GRAY_NOT_APPROVED",
                "message": "该账号尚未进入私信灰度名单",
                "messageId": message.id,
            },
        )
    if message.send_error == AccountCredentialExpiredError.__name__:
        return HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "ACCOUNT_CREDENTIAL_EXPIRED",
                "message": "抖音账号登录态已失效，请重新授权后再发送",
                "messageId": message.id,
            },
        )
    return HTTPException(
        status.HTTP_502_BAD_GATEWAY,
        detail={
            "code": "IM_SEND_FAILED",
            "message": "平台未确认发送成功，已记录失败，可重试或转人工处理",
            "messageId": message.id,
        },
    )


def _message_text(message: IMMessage) -> str:
    try:
        content = json.loads(message.content)
        if isinstance(content, dict):
            return str(content.get("text") or "")
    except (TypeError, ValueError):
        pass
    return message.content


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
        delivery_mode=inp.deliveryMode,
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
        "deliveryMode": "delivery_mode",
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
    await _require_gray_account(db, inp.accountId, user_id)
    control = await repo.get_global_control(db)
    if control is not None and control.stopped:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "IM_GLOBAL_STOPPED", "message": "管理员已停止私信监听，请稍后再试"},
        )

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


# ============ 自动发送授权与 Kill Switch ============


async def authorize_automation(
    db: AsyncSession,
    user_id: str,
    inp: AutomationConsentIn,
) -> AutomationStatusOut:
    await _require_owned_account(db, user_id, inp.accountId)
    await _require_gray_account(db, inp.accountId, user_id)
    if not inp.accepted:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "RISK_CONSENT_REQUIRED", "message": "必须明确同意自动回复风险协议"},
        )
    if inp.riskVersion != AUTOMATION_RISK_VERSION:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "RISK_VERSION_MISMATCH", "message": "风险协议版本已更新，请重新确认"},
        )
    consent = await repo.upsert_automation_consent(
        db,
        inp.accountId,
        user_id,
        inp.riskVersion,
        enabled=True,
    )
    return AutomationStatusOut(
        accountId=consent.account_id,
        authorized=consent.auto_reply_enabled,
        riskVersion=consent.risk_version,
        acceptedAt=consent.accepted_at.astimezone(UTC).isoformat(),
    )


async def disable_automation(db: AsyncSession, user_id: str, account_id: str) -> AutomationStatusOut:
    await _require_owned_account(db, user_id, account_id)
    await repo.disable_account_automation(db, account_id, user_id)
    consent = await repo.get_automation_consent(db, account_id, user_id)
    return AutomationStatusOut(
        accountId=account_id,
        authorized=False,
        riskVersion=consent.risk_version if consent else "",
        acceptedAt=consent.accepted_at.astimezone(UTC).isoformat() if consent else None,
    )


async def list_automation_status(db: AsyncSession, user_id: str) -> list[AutomationStatusOut]:
    consents = await repo.list_automation_consents(db, user_id)
    return [
        AutomationStatusOut(
            accountId=consent.account_id,
            authorized=consent.auto_reply_enabled,
            riskVersion=consent.risk_version,
            acceptedAt=consent.accepted_at.astimezone(UTC).isoformat(),
        )
        for consent in consents
    ]


async def set_global_kill_switch(db: AsyncSession, *, stopped: bool) -> int:
    return await repo.set_global_kill_switch(db, stopped=stopped)


async def get_global_kill_switch(db: AsyncSession) -> bool:
    control = await repo.get_global_control(db)
    return True if control is None else control.stopped


async def approve_gray_account(db: AsyncSession, account_id: str, admin_id: str) -> GrayAccountOut:
    account = await db.get(PublishAccount, account_id)
    if account is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "ACCOUNT_NOT_FOUND", "message": "发布账号不存在"},
        )
    settings = get_settings()
    try:
        gray = await repo.approve_gray_account(
            db,
            account_id,
            approved_by=admin_id,
            max_enabled=settings.im_gray_max_accounts,
        )
    except repo.GrayAccountLimitReached:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "IM_GRAY_LIMIT_REACHED", "message": "灰度账号数量已达到受控上限"},
        ) from None
    if gray is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail={"code": "ACCOUNT_NOT_FOUND", "message": "发布账号不存在"},
        )
    return GrayAccountOut(
        accountId=gray.account_id,
        userId=gray.user_id,
        nickname=account.nickname,
        approvedBy=gray.approved_by,
        addedAt=gray.created_at.astimezone(UTC).isoformat(),
    )


async def remove_gray_account(db: AsyncSession, account_id: str) -> bool:
    account = await db.get(PublishAccount, account_id)
    removed = await repo.remove_gray_account(db, account_id)
    if removed and account is not None:
        state = await repo.get_listener_state(db, account_id, account.user_id)
        if state is not None:
            state.status = "disconnected"
            state.error_msg = "gray_approval_removed"
            await db.commit()
        await repo.disable_account_automation(db, account_id, account.user_id, reason="GrayApprovalRemoved")
    return removed


async def list_gray_accounts(db: AsyncSession) -> list[GrayAccountOut]:
    return [
        GrayAccountOut(
            accountId=gray.account_id,
            userId=gray.user_id,
            nickname=account.nickname,
            approvedBy=gray.approved_by,
            addedAt=gray.created_at.astimezone(UTC).isoformat(),
        )
        for gray, account in await repo.list_gray_accounts(db)
    ]


async def get_monitoring_summary(db: AsyncSession, *, hours: int) -> MonitoringSummaryOut:
    now = datetime.now(UTC)
    since = now - timedelta(hours=hours)
    counts = await repo.metric_counts_since(db, since)
    gray, listeners, listening = await repo.gray_and_listener_counts(db)
    attempts = counts.get("listener_connect_attempt", 0)
    connected = counts.get("listener_connected", 0)
    dropouts = counts.get("listener_disconnected", 0) + counts.get("listener_error", 0)
    sent = counts.get("send_success", 0)
    failed = counts.get("send_failure", 0)
    return MonitoringSummaryOut(
        hours=hours,
        windowStart=since.isoformat(),
        windowEnd=now.isoformat(),
        grayAccounts=gray,
        listenerAccounts=listeners,
        listeningAccounts=listening,
        connectionAttempts=attempts,
        connectionSuccessRate=round(connected * 100 / attempts, 2) if attempts else 0.0,
        dropoutRate=round(dropouts * 100 / connected, 2) if connected else 0.0,
        sendSuccessRate=round(sent * 100 / (sent + failed), 2) if sent + failed else 0.0,
        sendSuccess=sent,
        sendFailure=failed,
        quotaRejected=counts.get("quota_rejected", 0),
        moderationBlocked=counts.get("moderation_blocked", 0),
        credentialExpired=counts.get("credential_expired", 0),
        ownershipRejected=counts.get("ownership_rejected", 0),
        riskControlIncidents=counts.get("risk_control_incident", 0),
    )


async def record_risk_control_incident(
    db: AsyncSession,
    inp: MonitoringIncidentIn,
) -> None:
    user_id = ""
    if inp.accountId:
        account = await db.get(PublishAccount, inp.accountId)
        if account is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail={"code": "ACCOUNT_NOT_FOUND", "message": "发布账号不存在"},
            )
        user_id = account.user_id
    await repo.record_metric_event(
        db,
        kind="risk_control_incident",
        account_id=inp.accountId,
        user_id=user_id,
        detail=inp.detail,
    )


async def expire_account_credentials(db: AsyncSession, account_id: str, user_id: str) -> bool:
    """Fail closed after a Douyin session expires and notify only on the first transition."""
    from app.core.audit import write_audit
    from app.modules.notify.service import notify_user
    from app.modules.publish import repository as publish_repo

    account = await publish_repo.get_account(db, account_id, user_id)
    if account is None:
        return False
    newly_expired = account.status != "expired"
    account.status = "expired"

    listener_state = await repo.get_listener_state(db, account_id, user_id)
    if listener_state is not None:
        listener_state.status = "error"
        listener_state.error_msg = "cookie_expired"
    canceled = await repo.disable_account_automation(
        db,
        account_id,
        user_id,
        reason="CredentialExpired",
    )
    logger.warning(
        "IM credentials expired: account=%s user=%s canceled=%d",
        account_id[:8],
        user_id[:8],
        canceled,
    )
    if newly_expired:
        await record_metric("credential_expired", account_id=account_id, user_id=user_id)

    if newly_expired:
        await write_audit(
            "im_account_credential_expired",
            user_id=user_id,
            detail=f"account_id={account_id},platform={account.platform}",
        )
        try:
            await notify_user(
                db,
                user_id,
                "warn",
                f"抖音账号「{account.nickname or account_id[:8]}」登录态失效，请重新授权",
                "私信监听和待发送自动回复已停止；请在账号管理中重新扫码授权后再手动恢复自动回复。",
            )
        except Exception:  # noqa: BLE001
            logger.exception("IM credential expiry notification failed: account=%s", account_id[:8])

    try:
        await emit(
            CHANNEL_IM,
            {
                "kind": EV_LISTENER_STATUS,
                "userId": user_id,
                "accountId": account_id,
                "status": "error",
                "errorMsg": "登录态失效，请重新绑定账号",
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("IM credential expiry event failed: account=%s", account_id[:8])
    return True


async def cleanup_expired_history() -> tuple[int, int]:
    from app.core.config import get_settings

    settings = get_settings()
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=max(1, settings.im_history_retention_days))
    metric_cutoff = now - timedelta(days=max(1, settings.im_metric_retention_days))
    async with SessionLocal() as db:
        deleted = await repo.cleanup_history(db, cutoff=cutoff)
        deleted_metrics = await repo.cleanup_metric_events(db, cutoff=metric_cutoff)
    logger.info(
        "IM history cleanup complete: messages=%d conversations=%d metrics=%d cutoff=%s metric_cutoff=%s",
        deleted[0],
        deleted[1],
        deleted_metrics,
        cutoff.isoformat(),
        metric_cutoff.isoformat(),
    )
    return deleted


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
    remote_message_id: str = "",
    remote_index: int | None = None,
) -> None:
    """Worker 收到新私信后的统一入口：落库 → 推送 → 触发自动回复"""
    async with _session() as db:
        from app.modules.publish import repository as publish_repo

        if not await publish_repo.get_account(db, account_id, user_id):
            logger.warning("ignored IM message with stale account ownership: account=%s", account_id[:8])
            await record_metric("ownership_rejected", account_id=account_id, user_id=user_id)
            return
        if get_settings().im_gray_enforced and not await repo.is_gray_account_enabled(db, account_id, user_id):
            logger.warning("ignored IM message outside gray allowlist: account=%s", account_id[:8])
            return

        # 1. 查找或创建会话
        conv = await repo.get_or_create_conversation(
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
            unread_count=0,
        )

        # 2. 消息落库
        content_json = json.dumps({"text": content}, ensure_ascii=False) if msg_type == 7 else content
        msg, created = await repo.create_remote_message(
            db,
            conversation_id=conv.id,
            user_id=user_id,
            direction="in",
            msg_type=msg_type,
            content=content_json,
            remote_message_id=remote_message_id or None,
            remote_index=remote_index,
        )
        if not created:
            return

        conv.last_message_at = datetime.now(UTC)
        conv.unread_count = (conv.unread_count or 0) + 1
        if remote_nickname:
            conv.remote_nickname = remote_nickname
        if remote_avatar:
            conv.remote_avatar = remote_avatar
        if dy_conversation_id:
            conv.dy_conversation_id = dy_conversation_id
        if dy_conversation_short_id:
            conv.dy_conversation_short_id = dy_conversation_short_id
        if dy_ticket:
            conv.dy_ticket = dy_ticket
        await repo.save_conversation(db, conv)

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

    # 生成回复内容
    reply_text = await _generate_reply(db, matched_rule, text, conv)
    if not reply_text:
        return

    from app.modules.im.moderation import review_outgoing

    moderation = review_outgoing(reply_text)
    if not moderation.allowed:
        await record_metric("moderation_blocked", account_id=conv.account_id, user_id=conv.user_id)
        await repo.create_message(
            db,
            conversation_id=conv.id,
            user_id=conv.user_id,
            direction="out",
            msg_type=7,
            content=json.dumps({"text": reply_text}, ensure_ascii=False),
            auto_replied=True,
            rule_id=matched_rule.id,
            send_status="blocked",
            moderation_status="blocked",
            moderation_reason=moderation.reason_text,
        )
        return

    listen_only = get_settings().im_listen_only
    if listen_only or matched_rule.delivery_mode != "auto":
        await repo.create_message(
            db,
            conversation_id=conv.id,
            user_id=conv.user_id,
            direction="out",
            msg_type=7,
            content=json.dumps({"text": reply_text}, ensure_ascii=False),
            auto_replied=True,
            rule_id=matched_rule.id,
            send_status="suggested",
            send_error="ListenOnlyMode" if listen_only and matched_rule.delivery_mode == "auto" else "",
            moderation_status="approved",
        )
        return

    block_reason = await repo.automation_block_reason(db, conv.account_id, conv.user_id)
    if block_reason:
        await repo.create_message(
            db,
            conversation_id=conv.id,
            user_id=conv.user_id,
            direction="out",
            msg_type=7,
            content=json.dumps({"text": reply_text}, ensure_ascii=False),
            auto_replied=True,
            rule_id=matched_rule.id,
            send_status="suggested",
            send_error=block_reason,
            moderation_status="approved",
        )
        return

    limiter = _get_reply_limiter()
    if not await limiter.reserve(
        account_id=conv.account_id,
        user_id=conv.user_id,
        rule_id=matched_rule.id,
        conversation_id=conv.id,
        minute_limit=MAX_REPLIES_PER_MINUTE,
        daily_limit=matched_rule.daily_limit,
        conversation_limit=MAX_REPLIES_PER_CONVERSATION_PER_DAY,
    ):
        logger.info("IM auto reply quota unavailable or exhausted: account=%s", conv.account_id[:8])
        await record_metric("quota_rejected", account_id=conv.account_id, user_id=conv.user_id)
        return

    # Persist the reply before publishing the delayed Dramatiq message.
    delay = random.uniform(max(0, matched_rule.delay_min), max(matched_rule.delay_min, matched_rule.delay_max))
    reply_message = await repo.create_message(
        db,
        conversation_id=conv.id,
        user_id=conv.user_id,
        direction="out",
        msg_type=7,
        content=json.dumps({"text": reply_text}, ensure_ascii=False),
        auto_replied=True,
        rule_id=matched_rule.id,
        send_status="scheduled",
        moderation_status="approved",
        scheduled_at=datetime.now(UTC) + timedelta(seconds=delay),
    )
    try:
        reply_message.queue_message_id = _schedule_auto_reply(reply_message.id, round(delay * 1000))
        await repo.save_message(db, reply_message)
    except Exception as error:  # noqa: BLE001
        reply_message.send_status = "failed"
        reply_message.send_error = error.__class__.__name__[:256]
        await repo.save_message(db, reply_message)
        logger.error("IM auto reply queue dispatch failed: message=%s", reply_message.id[:8])


def _schedule_auto_reply(message_id: str, delay_ms: int) -> str:
    from app.workers.tasks import run_im_auto_reply

    queued = run_im_auto_reply.send_with_options(args=(message_id,), delay=max(0, delay_ms))
    return queued.message_id


async def run_scheduled_reply(message_id: str) -> None:
    """Resume a durable auto reply using only its persisted message ID."""
    async with _session() as db:
        reply_msg = await repo.get_message_by_id(db, message_id)
        if reply_msg is None or reply_msg.send_status != "scheduled" or reply_msg.manual_takeover:
            return
        conv = await repo.get_conversation(db, reply_msg.conversation_id, reply_msg.user_id)
        if conv is None:
            reply_msg.send_status = "failed"
            reply_msg.send_error = "ConversationNotFound"
            await repo.save_message(db, reply_msg)
            return
        block_reason = await repo.automation_block_reason(db, conv.account_id, conv.user_id)
        if block_reason:
            reply_msg.send_status = "canceled"
            reply_msg.send_error = block_reason
            await repo.save_message(db, reply_msg)
            return
        if not await repo.claim_scheduled_message(db, reply_msg.id, reply_msg.user_id):
            return
        await db.refresh(reply_msg)
        try:
            await _send_existing_message(db, conv, reply_msg, _message_text(reply_msg))
        except Exception:  # noqa: BLE001
            return

    # 推送前端
    await emit(
        CHANNEL_IM,
        {
            "kind": EV_AUTO_REPLIED,
            "userId": reply_msg.user_id,
            "conversationId": reply_msg.conversation_id,
            "reply": _message_text(reply_msg),
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

    from app.modules.im.moderation import contains_prompt_injection

    if contains_prompt_injection(incoming_text):
        logger.warning("prompt injection blocked for IM conversation=%s", (conv.id or "")[:8])
        return rule.reply_template or ""

    # LLM mode is blocked unless the current IpAsset persona is readable.
    try:
        persona_ctx = await _get_persona_context(db, conv.user_id)
    except Exception as error:  # noqa: BLE001
        logger.warning("persona unavailable: user=%s error=%s", conv.user_id[:8], error.__class__.__name__)
        return rule.reply_template or ""
    if not persona_ctx:
        logger.warning("persona unavailable: user=%s no active persona", conv.user_id[:8])
        return rule.reply_template or ""

    try:
        llm = registry.get("llm")
        base_prompt = rule.llm_prompt or "请简洁友好地回复用户的私信。"
        prompt = f"{persona_ctx}\n{base_prompt}"
        reply = await llm.rewrite(text=incoming_text, intensity="light", prompt=prompt)
        return reply[:500]  # 限制长度
    except Exception as e:  # noqa: BLE001
        logger.warning(f"LLM reply generation failed: {e}")
        return rule.reply_template or ""


async def _get_persona_context(db: AsyncSession, user_id: str) -> str | None:
    """Read the current persona through the IpAsset service boundary."""
    from app.modules.ipasset import service as ip_service

    return await ip_service.get_active_persona_context(db, user_id)


# ============ 辅助 ============


def _get_reply_limiter():
    global _reply_limiter
    if _reply_limiter is None:
        from app.core.config import get_settings
        from app.modules.im.rate_limit import RedisReplyLimiter

        _reply_limiter = RedisReplyLimiter.from_url(get_settings().redis_url)
    return _reply_limiter


async def _load_account_session(account_id: str, user_id: str) -> dict:
    """#1 异步加载账号 session"""
    from app.modules.publish import repository as pub_repo

    async with SessionLocal() as db:
        if get_settings().im_gray_enforced and not await repo.is_gray_account_enabled(db, account_id, user_id):
            raise GrayAccountNotApprovedError("account is outside the IM gray allowlist")
        acc = await pub_repo.get_account(db, account_id, user_id)
        if acc and acc.status == "active":
            return pub_repo.account_session(acc)
        if acc:
            raise AccountCredentialExpiredError("account credentials expired")
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


async def _require_gray_account(db: AsyncSession, account_id: str, user_id: str) -> None:
    from app.core.config import get_settings

    if get_settings().im_gray_enforced and not await repo.is_gray_account_enabled(db, account_id, user_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"code": "IM_GRAY_NOT_APPROVED", "message": "该账号尚未进入私信灰度名单"},
        )


async def record_metric(
    kind: str,
    *,
    account_id: str = "",
    user_id: str = "",
    detail: str = "",
) -> None:
    """Persist monitoring without coupling business transactions to telemetry."""
    try:
        async with SessionLocal() as metric_db:
            await repo.record_metric_event(
                metric_db,
                kind=kind,
                account_id=account_id,
                user_id=user_id,
                detail=detail,
            )
    except Exception:  # noqa: BLE001
        logger.exception("IM metric write failed: kind=%s account=%s", kind, account_id[:8])


@asynccontextmanager
async def _session():
    async with SessionLocal() as db:
        yield db
