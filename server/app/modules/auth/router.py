"""auth HTTP 层

认证策略：
- 开户唯一入口：POST /activation/activate（激活码激活）
- 登录：POST /auth/login（手机号 + 密码，仅限已激活用户）
- 禁止手机号直接注册
- 登录防爆破：凭据错误按手机号 + IP 持久化计数，达限锁定（login_guard）
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import ADMIN_ROLES, get_current_user_id
from app.core.logging import get_logger
from app.core.middleware import resolve_client_ip

from . import repository as repo
from .login_guard import enforce_login_rate_limit, record_login_failure, record_login_success
from .schemas import ChangePasswordIn, LoginIn, RefreshIn, TokensOut, UpdatePhoneIn, UserOut
from .service import change_password, login, refresh, to_out, update_phone

router = APIRouter(prefix="/auth", tags=["auth"])
admin_router = APIRouter(prefix="/auth", tags=["admin-auth"])

logger = get_logger("oral.auth")


async def _guarded_login(
    db: AsyncSession,
    request: Request,
    body: LoginIn,
    *,
    required_roles: frozenset[str] | None = None,
    audience: str = "user",
) -> TokensOut:
    """带防爆破的登录：前置锁定检查 → 凭据错误计数 → 成功清零。

    计数读写失败（DB 抖动）不改变登录结果语义：仅降级记 warning，避免用户收到 500。
    """
    ip_address = resolve_client_ip(request)
    await enforce_login_rate_limit(body.phone, ip_address)
    try:
        tokens = await login(db, body.phone, body.password, body.deviceId, required_roles, audience)
    except HTTPException as exc:
        # 仅凭据错误计数；停用/未激活/无权限不计，避免被利用锁定他人账号
        if exc.status_code == 401:
            try:
                await record_login_failure(body.phone, ip_address)
            except Exception:  # noqa: BLE001 - 计数失败不阻断登录语义
                logger.warning("login_failure_count_error", error_type="record_failure")
        raise
    try:
        await record_login_success(body.phone, ip_address)
    except Exception:  # noqa: BLE001 - 清零失败遗留计数将由窗口过期自然消除
        logger.warning("login_success_count_error", error_type="record_success")
    return tokens


@router.post("/login", response_model=TokensOut)
async def api_login(body: LoginIn, request: Request, db: AsyncSession = Depends(get_db)):
    """手机号 + 密码登录（仅限已通过激活码激活的用户）"""
    return await _guarded_login(db, request, body)


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
async def api_admin_login(body: LoginIn, request: Request, db: AsyncSession = Depends(get_db)):
    """管理控制台登录：允许任一管理角色（admin/ops/finance/auditor），签发 admin audience 令牌。"""
    return await _guarded_login(db, request, body, required_roles=ADMIN_ROLES, audience="admin")
