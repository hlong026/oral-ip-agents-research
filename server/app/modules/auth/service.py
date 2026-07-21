"""auth 业务编排（F-601：注册登录 / JWT 双令牌 / 设备绑定 / 单端互踢可配置）
日志：登录成功/失败（§10.6.8-A #1，安全审计 DB 双写）
"""

from datetime import UTC

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.config import get_settings
from app.core.logging import get_logger, user_id_var
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

from . import repository as repo
from .models import User
from .schemas import TokensOut, UserOut

settings = get_settings()
logger = get_logger("oral.auth")


def _tokens(user_id: str, device_id: str | None, audience: str = "user") -> TokensOut:
    return TokensOut(
        accessToken=create_access_token(user_id, device_id, audience),
        refreshToken=create_refresh_token(user_id, device_id, audience),
        expiresIn=settings.access_token_ttl_min * 60,
    )


def _refresh_jti(tokens: TokensOut) -> str:
    payload = decode_token(tokens.refreshToken, "refresh")
    if payload is None:
        raise RuntimeError("自签 refresh_token 解码失败")
    return str(payload["jti"])


async def register(db: AsyncSession, phone: str, password: str, nickname: str) -> TokensOut:
    if await repo.get_by_phone(db, phone):
        logger.warning("register_failed", phone=phone, reason="PHONE_TAKEN")
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "PHONE_TAKEN", "message": "该手机号已注册"})
    user = await repo.create_user(db, phone, hash_password(password), nickname)
    tokens = _tokens(user.id, "web")
    await repo.save_session(db, user.id, "web", _refresh_jti(tokens))
    # 开户礼：初始额度
    from app.modules.billing.service import grant_initial_quota

    await grant_initial_quota(db, user.id)
    # 默认 IP 档案
    from app.modules.ipasset.service import create_default_persona

    await create_default_persona(db, user.id, user.nickname)
    logger.info("user_registered", user_id=user.id, phone=phone)
    await write_audit("user_registered", user_id=user.id, detail=f"phone={phone}")
    return tokens


async def login(
    db: AsyncSession,
    phone: str,
    password: str,
    device_id: str | None,
    required_role: str | None = None,
    audience: str = "user",
) -> TokensOut:
    user = await repo.get_by_phone(db, phone)
    if not user or not verify_password(password, user.password_hash):
        # 登录失败：记录 WARNING（安全审计）
        logger.warning("login_failed", phone=phone, reason="BAD_CREDENTIALS")
        await write_audit("login_failed", detail=f"phone={phone},reason=BAD_CREDENTIALS")
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={"code": "BAD_CREDENTIALS", "message": "手机号或密码错误"},
        )
    if not user.is_active:
        logger.warning("login_failed", phone=phone, user_id=user.id, reason="DISABLED")
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "DISABLED", "message": "账号已停用"})
    if required_role and user.role != required_role:
        logger.warning("login_failed", phone=phone, user_id=user.id, reason="ROLE_FORBIDDEN")
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "FORBIDDEN", "message": "账号无管理权限"})
    device = device_id or "web"
    if settings.single_session_kick:
        await repo.revoke_device_sessions(db, user.id, device)
    tokens = _tokens(user.id, device, audience)
    await repo.save_session(db, user.id, device, _refresh_jti(tokens))
    # 登录成功：记录 INFO + 设置 user_id 上下文
    user_id_var.set(user.id)
    logger.info("user_login", user_id=user.id, phone=phone, device=device)
    await write_audit("user_login", user_id=user.id, detail=f"phone={phone},device={device}")
    return tokens


async def refresh(db: AsyncSession, refresh_token: str) -> TokensOut:
    payload = decode_token(refresh_token, "refresh")
    if not payload or not await repo.is_jti_valid(db, payload["jti"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"code": "INVALID_REFRESH", "message": "刷新令牌无效"})
    user_id = str(payload["sub"])
    user = await repo.get_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "DISABLED", "message": "账号已停用"})
    device = payload.get("dev", "web")
    audience = str(payload.get("aud") or "user")
    tokens = _tokens(user_id, device, audience)
    await repo.rotate_refresh_session(db, str(payload["jti"]), user_id, device, _refresh_jti(tokens))
    return tokens


def to_out(user: User) -> UserOut:
    plan_expires_at = user.plan_expires_at
    activated_at = user.activated_at
    return UserOut(
        id=user.id,
        phone=user.phone,
        nickname=user.nickname,
        avatarChar=user.avatar_char,
        createdAt=user.created_at.astimezone(UTC).isoformat(),
        planType=getattr(user, "plan_type", "none") or "none",
        planExpiresAt=plan_expires_at.astimezone(UTC).isoformat() if plan_expires_at else None,
        activatedAt=activated_at.astimezone(UTC).isoformat() if activated_at else None,
    )
