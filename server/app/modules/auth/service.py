"""auth 业务编排（管理端密码登录 / JWT 双令牌 / 设备绑定 / 单端互踢可配置）
用户端登录走激活码链路（activation.service.login_with_code）。
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


async def admin_login(
    db: AsyncSession,
    phone: str,
    password: str,
    device_id: str | None,
) -> TokensOut:
    """管理端手机号+密码登录（仅 admin 角色，audience=admin）"""
    user = await repo.get_by_phone(db, phone)
    if not user or not user.password_hash or not verify_password(password, user.password_hash):
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
    if user.role != "admin":
        logger.warning("login_failed", phone=phone, user_id=user.id, reason="ROLE_FORBIDDEN")
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "FORBIDDEN", "message": "账号无管理权限"})
    device = device_id or "web"
    if settings.single_session_kick:
        await repo.revoke_device_sessions(db, user.id, device)
    tokens = _tokens(user.id, device, "admin")
    await repo.save_session(db, user.id, device, _refresh_jti(tokens))
    # 登录成功：记录 INFO + 设置 user_id 上下文
    user_id_var.set(user.id)
    logger.info("admin_login", user_id=user.id, phone=phone, device=device)
    await write_audit("admin_login", user_id=user.id, detail=f"phone={phone},device={device}")
    return tokens


async def refresh(db: AsyncSession, refresh_token: str, device_fingerprint: str = "") -> TokensOut:
    payload = decode_token(refresh_token, "refresh")
    if not payload or not await repo.is_jti_valid(db, payload["jti"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"code": "INVALID_REFRESH", "message": "刷新令牌无效"})
    user_id = str(payload["sub"])
    user = await repo.get_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "DISABLED", "message": "账号已停用"})
    audience = str(payload.get("aud") or "user")
    # 防拷贝：用户端刷新必须来自绑定设备（拷贝 refresh token 到其他机器无法续期）
    if audience == "user" and user.device_fingerprint and device_fingerprint != user.device_fingerprint:
        logger.warning("refresh_failed", user_id=user_id, reason="DEVICE_MISMATCH")
        await write_audit("refresh_failed", user_id=user_id, detail="reason=DEVICE_MISMATCH")
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"code": "DEVICE_MISMATCH", "message": "设备校验失败，请在绑定设备上使用"},
        )
    device = payload.get("dev", "web")
    tokens = _tokens(user_id, device, audience)
    await repo.rotate_refresh_session(db, str(payload["jti"]), user_id, device, _refresh_jti(tokens))
    return tokens


def to_out(user: User) -> UserOut:
    plan_expires_at = user.plan_expires_at
    activated_at = user.activated_at
    return UserOut(
        id=user.id,
        nickname=user.nickname,
        avatarChar=user.avatar_char,
        createdAt=user.created_at.astimezone(UTC).isoformat(),
        planType=getattr(user, "plan_type", "none") or "none",
        planExpiresAt=plan_expires_at.astimezone(UTC).isoformat() if plan_expires_at else None,
        activatedAt=activated_at.astimezone(UTC).isoformat() if activated_at else None,
        deviceBound=bool(user.device_fingerprint),
    )
