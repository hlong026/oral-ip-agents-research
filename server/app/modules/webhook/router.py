"""Webhook 回调接收端点（内部使用，白标不暴露供应商品牌）"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db

from .service import handle_callback

router = APIRouter(prefix="/webhooks", tags=["webhook"])


@router.post("/hifly")
async def webhook_hifly(request: Request, db: AsyncSession = Depends(get_db)):
    """
    供应商任务完成回调统一入口
    按 type 分发：1=创作 2=数字人克隆 3=声音克隆
    幂等处理：task_id 去重
    """
    payload = await request.json()
    await handle_callback(db, payload)
    return {"ok": True}
