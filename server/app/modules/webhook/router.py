"""Webhook 回调接收端点（内部使用，白标不暴露供应商品牌）"""

import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db

from .service import handle_callback

router = APIRouter(prefix="/webhooks", tags=["webhook"])
_settings = get_settings()


@router.post("/provider-callback")
@router.post("/hifly", include_in_schema=False)
async def webhook_provider_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """
    供应商任务完成回调统一入口
    按 type 分发：1=创作 2=数字人克隆 3=声音克隆
    幂等处理：event_id + task_id 双重去重
    安全：生产环境强制 HMAC-SHA256 验签
    """
    body = await request.body()
    secret = _settings.feiying_webhook_secret
    if not secret and _settings.app_env not in {"dev", "test"}:
        raise HTTPException(
            status_code=503,
            detail={"code": "WEBHOOK_DISABLED", "message": "回调验签未配置"},
        )
    if secret:
        sig = request.headers.get("X-Signature", "")
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise HTTPException(
                status_code=403,
                detail={"code": "BAD_SIGNATURE", "message": "回调签名校验失败"},
            )
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_WEBHOOK", "message": "回调内容不是有效 JSON"},
        ) from exc
    processed = await handle_callback(
        db,
        payload,
        event_id=request.headers.get("X-Event-Id", ""),
    )
    return {"ok": True, "processed": processed}
