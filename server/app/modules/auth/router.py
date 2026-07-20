"""auth HTTP 层（仅参数校验与调用 service）"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_current_user_id

from . import repository as repo
from .schemas import LoginIn, RefreshIn, RegisterIn, TokensOut, UserOut
from .service import login, refresh, register, to_out

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokensOut)
async def api_register(body: RegisterIn, db: AsyncSession = Depends(get_db)):
    return await register(db, body.phone, body.password, body.nickname)


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
