"""auth HTTP 层（仅参数校验与调用 service）"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user_id_ignore_plan

from . import repository as repo
from .schemas import AdminLoginIn, CodeLoginIn, RefreshIn, TokensOut, UserOut
from .service import admin_login, refresh, to_out

router = APIRouter(prefix="/auth", tags=["auth"])
admin_router = APIRouter(prefix="/auth", tags=["admin-auth"])


@router.post("/login", response_model=TokensOut)
async def api_login(body: CodeLoginIn, request: Request, db: AsyncSession = Depends(get_db)):
    """用户端激活码登录（未使用码首次登录即开户）"""
    from app.modules.activation.rate_limit import enforce_rate_limit, record_attempt
    from app.modules.activation.service import login_with_code

    ip_address = request.client.host if request.client else "unknown"
    await enforce_rate_limit(
        "login",
        ip_address=ip_address,
        device_fingerprint=body.deviceFingerprint,
        code=body.code,
    )
    try:
        result = await login_with_code(db, body.code, body.deviceFingerprint)
    except HTTPException:
        await db.rollback()
        await record_attempt(
            "login",
            success=False,
            ip_address=ip_address,
            device_fingerprint=body.deviceFingerprint,
            code=body.code,
        )
        raise
    await record_attempt(
        "login",
        success=True,
        ip_address=ip_address,
        device_fingerprint=body.deviceFingerprint,
        code=body.code,
    )
    return result


@router.post("/refresh", response_model=TokensOut)
async def api_refresh(body: RefreshIn, db: AsyncSession = Depends(get_db)):
    return await refresh(db, body.refreshToken, body.deviceFingerprint)


@router.get("/me", response_model=UserOut)
async def api_me(user_id: str = Depends(get_current_user_id_ignore_plan), db: AsyncSession = Depends(get_db)):
    user = await repo.get_by_id(db, user_id)
    return to_out(user)  # type: ignore[arg-type]


@admin_router.post("/login", response_model=TokensOut)
async def api_admin_login(body: AdminLoginIn, db: AsyncSession = Depends(get_db)):
    return await admin_login(db, body.phone, body.password, body.deviceId)
