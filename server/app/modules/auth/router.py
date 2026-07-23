"""auth HTTP 层

认证策略：
- 开户唯一入口：POST /activation/activate（激活码激活）
- 登录：POST /auth/login（手机号 + 密码，仅限已激活用户）
- 禁止手机号直接注册
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user_id

from . import repository as repo
from .schemas import ChangePasswordIn, LoginIn, RefreshIn, TokensOut, UpdatePhoneIn, UserOut
from .service import change_password, login, refresh, to_out, update_phone

router = APIRouter(prefix="/auth", tags=["auth"])
admin_router = APIRouter(prefix="/auth", tags=["admin-auth"])


@router.post("/login", response_model=TokensOut)
async def api_login(body: LoginIn, db: AsyncSession = Depends(get_db)):
    """手机号 + 密码登录（仅限已通过激活码激活的用户）"""
    return await login(db, body.phone, body.password, body.deviceId)


@router.post("/refresh", response_model=TokensOut)
async def api_refresh(body: RefreshIn, db: AsyncSession = Depends(get_db)):
    return await refresh(db, body.refreshToken)


@router.get("/me", response_model=UserOut)
async def api_me(user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    user = await repo.get_by_id(db, user_id)
    return to_out(user)  # type: ignore[arg-type]


@router.post("/change-password", status_code=204)
async def api_change_password(
    body: ChangePasswordIn,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """修改密码（修改后所有设备需重新登录）"""
    await change_password(db, user_id, body.oldPassword, body.newPassword)


@router.put("/phone", response_model=UserOut)
async def api_update_phone(
    body: UpdatePhoneIn,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """换绑手机号（需验证当前密码）"""
    return await update_phone(db, user_id, body.newPhone, body.password)


@admin_router.post("/login", response_model=TokensOut)
async def api_admin_login(body: LoginIn, db: AsyncSession = Depends(get_db)):
    return await login(db, body.phone, body.password, body.deviceId, required_role="admin", audience="admin")
