"""Webhook 回调接收端点（内部使用，白标不暴露供应商品牌）"""
import hashlib
import hmac

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db

from .service import handle_callback

router = APIRouter(prefix="/webhooks", tags=["webhook"])
_settings = get_settings()


@router.post("/hifly")
async def webhook_hifly(request: Request, db: AsyncSession = Depends(get_db)):
    """
    供应商任务完成回调统一入口
    按 type 分发：1=创作 2=数字人克隆 3=声音克隆
    幂等处理：task_id 去重
    安全：配置了 feiying_webhook_secret 时进行 HMAC-SHA256 验签
    """
    body = await request.body()
    if _settings.feiying_webhook_secret:
        sig = request.headers.get("X-Signature", "")
        expected = hmac.new(
            _settings.feiying_webhook_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise HTTPException(
                status_code=403,
                detail={"code": "BAD_SIGNATURE", "message": "回调签名校验失败"},
            )
    import json as _json
    payload = _json.loads(body)
    await handle_callback(db, payload)
    return {"ok": True}
