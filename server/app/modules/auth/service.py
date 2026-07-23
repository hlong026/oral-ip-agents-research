"""auth 业务编排（激活码开户 + 手机号密码登录 / JWT 双令牌 / 设备绑定 / 单端互踢可配置）

认证策略：
- 禁止通过手机号直接注册，开户唯一入口为激活码激活
- 激活时绑定手机号 + 密码，后续通过手机号 + 密码登录
- 支持已登录用户修改密码和换绑手机号

日志：登录成功/失败（§10.6.8-A #1，安全审计 DB 双写）
"""

from datetime import UTC
from typing import Literal, cast

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
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


async def login(
    db: AsyncSession,
    phone: str,
    password: str,
    device_id: str | None,
    required_roles: frozenset[str] | None = None,
    audience: str = "user",
) -> TokensOut:
    """手机号 + 密码登录（仅限已通过激活码激活的用户）

    required_roles：管理面登录时传入允许的角色集合（ADMIN_ROLES），
    普通用户登录留空即可。
    """
    user = await repo.get_by_phone(db, phone)
    if not user or not verify_password(password, user.password_hash):
        logger.warning("login_failed", phone=phone, reason="BAD_CREDENTIALS")
        await write_audit("login_failed", detail=f"phone={phone},reason=BAD_CREDENTIALS")
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail={"code": "BAD_CREDENTIALS", "message": "手机号或密码错误"},
        )
    if not user.is_active:
        logger.warning("login_failed", phone=phone, user_id=user.id, reason="DISABLED")
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "DISABLED", "message": "账号已停用"})
    if user.activated_at is None:
        logger.warning("login_failed", phone=phone, user_id=user.id, reason="NOT_ACTIVATED")
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"code": "NOT_ACTIVATED", "message": "账号未激活，请先使用激活码激活"},
        )
    if required_roles and user.role not in required_roles:
        logger.warning("login_failed", phone=phone, user_id=user.id, reason="ROLE_FORBIDDEN")
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "FORBIDDEN", "message": "账号无管理权限"})
    device = device_id or "web"
    if settings.single_session_kick:
        await repo.revoke_device_sessions(db, user.id, device)
    tokens = _tokens(user.id, device, audience)
    await repo.save_session(db, user.id, device, _refresh_jti(tokens))
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


async def change_password(db: AsyncSession, user_id: str, old_password: str, new_password: str) -> None:
    """已登录用户修改密码"""
    user = await repo.get_by_id(db, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "用户不存在"})
    if not verify_password(old_password, user.password_hash):
        logger.warning("change_password_failed", user_id=user_id, reason="OLD_PASSWORD_WRONG")
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "OLD_PASSWORD_WRONG", "message": "当前密码错误"},
        )
    if old_password == new_password:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "SAME_PASSWORD", "message": "新密码不能与当前密码相同"},
        )
    await repo.update_password_and_revoke_sessions(db, user_id, hash_password(new_password))
    logger.info("password_changed", user_id=user_id)
    await write_audit("password_changed", user_id=user_id)


async def update_phone(db: AsyncSession, user_id: str, new_phone: str, password: str) -> UserOut:
    """已登录用户换绑手机号（需验证当前密码）"""
    user = await repo.get_by_id(db, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "NOT_FOUND", "message": "用户不存在"})
    if not verify_password(password, user.password_hash):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "PASSWORD_WRONG", "message": "密码验证失败"},
        )
    existing = await repo.get_by_phone(db, new_phone)
    if existing and existing.id != user_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "PHONE_TAKEN", "message": "该手机号已被其他账号绑定"},
        )
    old_phone = user.phone
    try:
        await repo.update_phone(db, user_id, new_phone)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "PHONE_TAKEN", "message": "该手机号已被其他账号绑定"},
        )
    logger.info("phone_updated", user_id=user_id, old_phone=old_phone, new_phone=new_phone)
    await write_audit("phone_updated", user_id=user_id, detail=f"old={old_phone},new={new_phone}")
    updated_user = await repo.get_by_id(db, user_id)
    return to_out(updated_user)  # type: ignore[arg-type]


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
        role=cast(Literal["user", "admin", "ops", "finance", "auditor"], user.role),
    )
