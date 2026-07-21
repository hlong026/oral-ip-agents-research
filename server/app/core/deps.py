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
    db: AsyncSession = Depends(get_db),
) -> str:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"code": "UNAUTHORIZED", "message": "未登录"})
    payload = decode_token(cred.credentials, "access")
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"code": "UNAUTHORIZED", "message": "登录已过期"})
    if payload.get("aud") != "user":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "FORBIDDEN", "message": "请使用用户端登录"})
    uid = str(payload["sub"])
    from app.modules.auth.repository import get_by_id

    user = await get_by_id(db, uid)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "DISABLED", "message": "账号已停用"})
    user_id_var.set(uid)  # 注入上下文，后续日志自动携带 user_id
    return uid


async def get_current_access_payload(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> dict:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"code": "UNAUTHORIZED", "message": "未登录"})
    payload = decode_token(cred.credentials, "access")
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"code": "UNAUTHORIZED", "message": "登录已过期"})
    user_id_var.set(str(payload["sub"]))
    return payload


async def require_admin(
    payload: dict = Depends(get_current_access_payload),
    db: AsyncSession = Depends(get_db),
) -> str:
    """管理控制面鉴权：必须是启用中的 admin 用户，且使用 admin audience 登录。"""
    from app.modules.auth.repository import get_by_id

    if payload.get("aud") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "FORBIDDEN", "message": "需要管理员登录"})
    user_id = str(payload["sub"])
    user = await get_by_id(db, user_id)
    if not user or not user.is_active or user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "FORBIDDEN", "message": "需要管理员权限"})
    return user_id


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
    return str(payload["sub"]) if payload and payload.get("aud") == "user" else None
