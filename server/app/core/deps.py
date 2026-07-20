"""FastAPI 依赖：当前用户、DB 会话"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .logging import user_id_var
from .security import decode_token

bearer = HTTPBearer(auto_error=False)


async def get_current_user_id(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"code": "UNAUTHORIZED", "message": "未登录"})
    payload = decode_token(cred.credentials, "access")
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"code": "UNAUTHORIZED", "message": "登录已过期"})
    uid = str(payload["sub"])
    user_id_var.set(uid)  # 注入上下文，后续日志自动携带 user_id
    return uid


async def get_current_active_persona_id(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> str | None:
    """当前激活 IP（IP 切换器全局生效）"""
    from app.modules.ipasset.service import get_active_persona_id

    return await get_active_persona_id(db, user_id)


def verify_ws_token(token: str) -> str | None:
    """WS 网关 token 校验（/ws/tasks?token=）"""
    payload = decode_token(token, "access")
    return str(payload["sub"]) if payload else None
