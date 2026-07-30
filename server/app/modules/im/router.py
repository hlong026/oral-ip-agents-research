"""im 模块 HTTP 路由（私信中心 + 建议回复规则 + 监听控制）"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.db import get_db
from app.core.deps import get_current_user_id, require_admin

from . import service
from .schemas import (
    ConversationPageOut,
    GrayAccountOut,
    KillSwitchIn,
    KillSwitchOut,
    ListenerControlIn,
    ListenerStatusOut,
    MessageOut,
    MessagePageOut,
    MonitoringIncidentIn,
    MonitoringSummaryOut,
    RuleCreateIn,
    RuleOut,
    RuleUpdateIn,
)

router = APIRouter(prefix="/im", tags=["im"])
admin_router = APIRouter(prefix="/im", tags=["admin-im"])


# ---- 会话 ----


@router.get("/conversations", response_model=ConversationPageOut)
async def list_conversations(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    search: str = Query("", max_length=100),
    accountId: str = Query("", max_length=32),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    return await service.list_conversations(db, user_id, page, pageSize, search, accountId)


@router.get("/conversations/{conversation_id}/messages", response_model=MessagePageOut)
async def list_messages(
    conversation_id: str,
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=200),
    search: str = Query("", max_length=100),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    return await service.list_messages(db, user_id, conversation_id, page, pageSize, search)


@router.put("/conversations/{conversation_id}/read")
async def mark_read(
    conversation_id: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_id)
):
    await service.mark_read(db, user_id, conversation_id)
    return {"ok": True}


@router.post("/messages/{message_id}/takeover", response_model=MessageOut)
async def take_over_message(
    message_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    return await service.take_over_message(db, user_id, message_id)


# ---- 建议回复规则 ----


@router.get("/rules", response_model=list[RuleOut])
async def list_rules(db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    return await service.list_rules(db, user_id)


@router.post("/rules", response_model=RuleOut, status_code=201)
async def create_rule(
    inp: RuleCreateIn, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_id)
):
    return await service.create_rule(db, user_id, inp)


@router.put("/rules/{rule_id}", response_model=RuleOut)
async def update_rule(
    rule_id: str, inp: RuleUpdateIn, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_id)
):
    return await service.update_rule(db, user_id, rule_id, inp)


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    await service.delete_rule(db, user_id, rule_id)
    return {"ok": True}


@router.put("/rules/{rule_id}/toggle", response_model=RuleOut)
async def toggle_rule(rule_id: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    return await service.toggle_rule(db, user_id, rule_id)


# ---- 监听控制 ----


@router.get("/listener/status", response_model=list[ListenerStatusOut])
async def listener_status(db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    return await service.get_listener_status(db, user_id)


@router.post("/listener/start", response_model=ListenerStatusOut)
async def start_listener(
    inp: ListenerControlIn, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_id)
):
    return await service.start_listener(db, user_id, inp)


@router.post("/listener/stop", response_model=ListenerStatusOut)
async def stop_listener(
    inp: ListenerControlIn, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_id)
):
    return await service.stop_listener(db, user_id, inp)


@admin_router.put("/kill-switch", response_model=KillSwitchOut)
async def set_kill_switch(
    inp: KillSwitchIn,
    db: AsyncSession = Depends(get_db),
    admin_id: str = Depends(require_admin),
):
    canceled = await service.set_global_kill_switch(db, stopped=inp.stopped)
    await write_audit(
        "im_global_kill_switch_updated",
        user_id=admin_id,
        detail=f"stopped={inp.stopped},canceled={canceled}",
    )
    return KillSwitchOut(stopped=inp.stopped, canceledMessages=canceled)


@admin_router.get("/kill-switch", response_model=KillSwitchOut)
async def get_kill_switch(
    db: AsyncSession = Depends(get_db),
    _admin_id: str = Depends(require_admin),
):
    stopped = await service.get_global_kill_switch(db)
    return KillSwitchOut(stopped=stopped)


@admin_router.get("/gray/accounts", response_model=list[GrayAccountOut])
async def list_gray_accounts(
    db: AsyncSession = Depends(get_db),
    _admin_id: str = Depends(require_admin),
):
    return await service.list_gray_accounts(db)


@admin_router.put("/gray/accounts/{account_id}", response_model=GrayAccountOut)
async def approve_gray_account(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    admin_id: str = Depends(require_admin),
):
    gray = await service.approve_gray_account(db, account_id, admin_id)
    await write_audit("im_gray_account_approved", user_id=admin_id, detail=f"account_id={account_id}")
    return gray


@admin_router.delete("/gray/accounts/{account_id}")
async def remove_gray_account(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    admin_id: str = Depends(require_admin),
):
    removed = await service.remove_gray_account(db, account_id)
    await write_audit(
        "im_gray_account_removed",
        user_id=admin_id,
        detail=f"account_id={account_id},removed={removed}",
    )
    return {"ok": removed}


@admin_router.get("/monitoring", response_model=MonitoringSummaryOut)
async def monitoring_summary(
    hours: int = Query(24, ge=1, le=24 * 30),
    db: AsyncSession = Depends(get_db),
    _admin_id: str = Depends(require_admin),
):
    return await service.get_monitoring_summary(db, hours=hours)


@admin_router.post("/monitoring/incidents", status_code=201)
async def record_monitoring_incident(
    inp: MonitoringIncidentIn,
    db: AsyncSession = Depends(get_db),
    admin_id: str = Depends(require_admin),
):
    await service.record_risk_control_incident(db, inp)
    await write_audit(
        "im_risk_control_incident_recorded",
        user_id=admin_id,
        detail=f"account_id={inp.accountId},detail={inp.detail}",
    )
    return {"ok": True}
