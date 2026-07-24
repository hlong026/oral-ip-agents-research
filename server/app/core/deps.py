"""FastAPI 依赖：当前用户、DB 会话、管理控制面 RBAC"""

from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .logging import user_id_var
from .security import decode_token

bearer = HTTPBearer(auto_error=False)

# ---- 管理控制面 RBAC ----
# 可登录管理端的角色集合（User.role 取其一；user 为纯数据面角色）
ADMIN_ROLES: frozenset[str] = frozenset({"admin", "ops", "finance", "auditor"})

# 角色 → 权限点映射。"*" 为超管通配。
# - admin:   全部权限（含用户角色变更、Provider 密钥管理）
# - ops:     运营（用户查看/停用、激活码批次、IM 安全）
# - finance: 财务（积分调整、套餐与价格版本、成本分析）
# - auditor: 只读审计（列表/审计日志/成本查看，无任何写操作）
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset({"*"}),
    "ops": frozenset({"users.read", "users.write", "activation.read", "activation.manage", "im.manage", "audit.read"}),
    "finance": frozenset({"users.read", "billing.adjust", "catalog.read", "catalog.manage", "cost.read", "audit.read"}),
    "auditor": frozenset({"users.read", "activation.read", "catalog.read", "cost.read", "audit.read"}),
}


async def get_current_user_id(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> str:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"code": "UNAUTHORIZED", "message": "未登录"})
    # 用户数据面：强制使用用户面密钥验证（管理面令牌无法在此使用）
    payload = decode_token(cred.credentials, "access", audience="user")
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"code": "UNAUTHORIZED", "message": "登录已过期"})
    uid = str(payload["sub"])
    from app.modules.auth.repository import get_by_id

    user = await get_by_id(db, uid)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "DISABLED", "message": "账号已停用"})
    user_id_var.set(uid)  # 注入上下文，后续日志自动携带 user_id
    return uid


async def _authenticate_admin(
    cred: HTTPAuthorizationCredentials | None,
    db: AsyncSession,
) -> tuple[str, str]:
    """管理面身份认证：admin audience 密钥验证 + 启用中 + 管理角色。返回 (user_id, role)。"""
    from app.modules.auth.repository import get_by_id

    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"code": "UNAUTHORIZED", "message": "未登录"})
    # 管理控制面：强制使用管理面专用密钥验证（用户面密钥伪造的令牌在此失败）
    payload = decode_token(cred.credentials, "access", audience="admin")
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={"code": "UNAUTHORIZED", "message": "登录已过期"})
    user_id = str(payload["sub"])
    user = await get_by_id(db, user_id)
    if not user or not user.is_active or user.role not in ADMIN_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": "FORBIDDEN", "message": "需要管理员权限"})
    user_id_var.set(user_id)
    return user_id, user.role


async def require_admin(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> str:
    """管理控制面鉴权：admin audience + 启用中 + 任一管理角色（不区分权限点）。"""
    user_id, _role = await _authenticate_admin(cred, db)
    return user_id


def require_permission(permission: str) -> Callable[..., Awaitable[str]]:
    """路由级权限点校验（RBAC）。超管拥有 "*" 通配，其余角色按 ROLE_PERMISSIONS 判定。"""

    async def dependency(
        cred: HTTPAuthorizationCredentials | None = Depends(bearer),
        db: AsyncSession = Depends(get_db),
    ) -> str:
        user_id, role = await _authenticate_admin(cred, db)
        perms = ROLE_PERMISSIONS.get(role, frozenset())
        if "*" not in perms and permission not in perms:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail={"code": "FORBIDDEN", "message": "当前管理角色缺少所需权限"},
            )
        return user_id

    return dependency


async def get_current_active_persona_id(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> str | None:
    """当前激活 IP（IP 切换器全局生效）"""
    from app.modules.ipasset.service import get_active_persona_id

    return await get_active_persona_id(db, user_id)


def verify_ws_token(token: str) -> str | None:
    """校验 WebSocket 子协议携带的用户 access token。"""
    payload = decode_token(token, "access", audience="user")
    return str(payload["sub"]) if payload else None
