"""im 模块 HTTP 路由（私信中心 + 自动回复规则 + 监听控制）"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user_id

from . import service
from .schemas import (
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

router = APIRouter(prefix="/im", tags=["im"])


# ---- 会话 ----


@router.get("/conversations", response_model=ConversationPageOut)
async def list_conversations(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    return await service.list_conversations(db, user_id, page, pageSize)


@router.get("/conversations/{conversation_id}/messages", response_model=MessagePageOut)
async def list_messages(
    conversation_id: str,
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    return await service.list_messages(db, user_id, conversation_id, page, pageSize)


@router.post("/conversations/{conversation_id}/send", response_model=MessageOut)
async def send_message(
    conversation_id: str,
    inp: SendMessageIn,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
):
    return await service.send_message(db, user_id, conversation_id, inp)


@router.put("/conversations/{conversation_id}/read")
async def mark_read(
    conversation_id: str, db: AsyncSession = Depends(get_db), user_id: str = Depends(get_current_user_id)
):
    await service.mark_read(db, user_id, conversation_id)
    return {"ok": True}


# ---- 自动回复规则 ----


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
