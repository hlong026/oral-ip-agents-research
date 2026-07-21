"""auth HTTP 层（仅参数校验与调用 service）"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user_id

from . import repository as repo
from .schemas import LoginIn, RefreshIn, TokensOut, UserOut
from .service import login, refresh, to_out

router = APIRouter(prefix="/auth", tags=["auth"])
admin_router = APIRouter(prefix="/auth", tags=["admin-auth"])


@router.post("/login", response_model=TokensOut)
async def api_login(body: LoginIn, db: AsyncSession = Depends(get_db)):
    return await login(db, body.phone, body.password, body.deviceId)


@router.post("/refresh", response_model=TokensOut)
async def api_refresh(body: RefreshIn, db: AsyncSession = Depends(get_db)):
    return await refresh(db, body.refreshToken)


@router.get("/me", response_model=UserOut)
async def api_me(user_id: str = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    user = await repo.get_by_id(db, user_id)
    return to_out(user)  # type: ignore[arg-type]


@admin_router.post("/login", response_model=TokensOut)
async def api_admin_login(body: LoginIn, db: AsyncSession = Depends(get_db)):
    return await login(db, body.phone, body.password, body.deviceId, required_role="admin", audience="admin")
